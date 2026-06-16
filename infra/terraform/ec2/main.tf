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
      var.mcp_bearer_token_ssm_parameter_name,
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
      var.mcp_bearer_token_kms_key_arn,
    ] : arn
    if arn != null
  ]

  ecr_registry       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.${data.aws_partition.current.dns_suffix}"
  llm_wiki_image_uri = "${aws_ecr_repository.llm_wiki.repository_url}:${var.container_image_tag}"
  wiki_ui_image_uri  = "${aws_ecr_repository.wiki_ui.repository_url}:${var.container_image_tag}"

  github_oidc_provider_arn = var.github_actions_oidc_provider_arn != null ? var.github_actions_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
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

resource "aws_ecr_repository" "llm_wiki" {
  name                 = "${var.project_name}/llm-wiki"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "wiki_ui" {
  name                 = "${var.project_name}/wiki-ui"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "llm_wiki" {
  repository = aws_ecr_repository.llm_wiki.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "wiki_ui" {
  repository = aws_ecr_repository.wiki_ui.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
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

resource "aws_vpc_security_group_ingress_rule" "http" {
  for_each = toset(var.allowed_http_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "Caddy HTTP and Lets Encrypt HTTP-01"
  cidr_ipv4         = each.value
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  for_each = toset(var.allowed_https_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "Caddy HTTPS"
  cidr_ipv4         = each.value
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
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

data "aws_iam_policy_document" "ecr_pull" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [
      aws_ecr_repository.llm_wiki.arn,
      aws_ecr_repository.wiki_ui.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecr_pull" {
  name   = "${var.project_name}-ecr-pull"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.ecr_pull.json
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.github_actions_oidc_provider_arn == null ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_actions_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_ecr" {
  name               = "${var.project_name}-github-actions-ecr"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
}

data "aws_iam_policy_document" "github_actions_ecr_push" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [
      aws_ecr_repository.llm_wiki.arn,
      aws_ecr_repository.wiki_ui.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name   = "${var.project_name}-ecr-push"
  role   = aws_iam_role.github_actions_ecr.id
  policy = data.aws_iam_policy_document.github_actions_ecr_push.json
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
    ecr_registry                              = local.ecr_registry
    llm_wiki_image                            = local.llm_wiki_image_uri
    mcp_bearer_token_ssm_parameter_name       = coalesce(var.mcp_bearer_token_ssm_parameter_name, "")
    wiki_domain_name                          = var.domain_name
    wiki_data_repo_ssh_key_ssm_parameter_name = coalesce(var.wiki_data_repo_ssh_key_ssm_parameter_name, "")
    wiki_data_repository_url                  = coalesce(var.wiki_data_repository_url, "")
    wiki_ui_image                             = local.wiki_ui_image_uri
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

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.app.id

  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${var.project_name}-eip"
  }
}
