locals {
  common_tags = merge(
    {
      Project   = var.project_name
      ManagedBy = "terraform"
    },
    var.tags,
  )

  ssh_key_ssm_parameter_names = [
    for name in [
      var.app_repo_ssh_key_ssm_parameter_name,
      var.wiki_data_repo_ssh_key_ssm_parameter_name,
    ] : name
    if name != null
  ]

  ssh_key_ssm_parameter_paths = [
    for name in local.ssh_key_ssm_parameter_names :
    startswith(name, "/") ? name : "/${name}"
  ]

  ssh_key_ssm_parameter_arns = [
    for path in local.ssh_key_ssm_parameter_paths :
    "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${path}"
  ]

  ssh_key_kms_key_arns = [
    for arn in [
      var.app_repo_ssh_key_kms_key_arn,
      var.wiki_data_repo_ssh_key_kms_key_arn,
    ] : arn
    if arn != null
  ]
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = coalesce(var.availability_zone, data.aws_availability_zones.available.names[0])
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-public"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "app" {
  name        = "${var.project_name}-sg"
  description = "Access to llm-wiki EC2 deployment"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ui" {
  for_each = toset(var.allowed_ui_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "Hugo wiki UI"
  cidr_ipv4         = each.value
  from_port         = var.wiki_ui_port
  ip_protocol       = "tcp"
  to_port           = var.wiki_ui_port
}

resource "aws_vpc_security_group_ingress_rule" "mcp" {
  for_each = toset(var.allowed_mcp_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "llm-wiki MCP HTTP"
  cidr_ipv4         = each.value
  from_port         = var.mcp_port
  ip_protocol       = "tcp"
  to_port           = var.mcp_port
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each = toset(var.allowed_ssh_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "SSH"
  cidr_ipv4         = each.value
  from_port         = 22
  ip_protocol       = "tcp"
  to_port           = 22
}

resource "aws_vpc_security_group_egress_rule" "all_ipv4" {
  security_group_id = aws_security_group.app.id
  description       = "All outbound IPv4"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.project_name}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count = var.enable_ssm ? 1 : 0

  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "ssh_keys_ssm" {
  count = length(local.ssh_key_ssm_parameter_names) > 0 ? 1 : 0

  statement {
    actions   = ["ssm:GetParameter"]
    resources = local.ssh_key_ssm_parameter_arns
  }

  dynamic "statement" {
    for_each = length(local.ssh_key_kms_key_arns) > 0 ? [local.ssh_key_kms_key_arns] : []
    iterator = kms_key_arns

    content {
      actions   = ["kms:Decrypt"]
      resources = kms_key_arns.value
    }
  }
}

resource "aws_iam_role_policy" "ssh_keys_ssm" {
  count = length(local.ssh_key_ssm_parameter_names) > 0 ? 1 : 0

  name   = "${var.project_name}-ssh-keys-ssm"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.ssh_keys_ssm[0].json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.app.name
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.app.name
  key_name                    = var.key_name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    app_dir                                   = var.app_dir
    app_repo_ssh_key_ssm_parameter_name       = coalesce(var.app_repo_ssh_key_ssm_parameter_name, "")
    app_repository_ref                        = var.app_repository_ref
    app_repository_url                        = var.app_repository_url
    aws_region                                = var.aws_region
    docker_compose_version                    = var.docker_compose_version
    wiki_data_repo_ssh_key_ssm_parameter_name = coalesce(var.wiki_data_repo_ssh_key_ssm_parameter_name, "")
    wiki_data_repository_url                  = coalesce(var.wiki_data_repository_url, "")
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = "${var.project_name}-ec2"
  }
}
