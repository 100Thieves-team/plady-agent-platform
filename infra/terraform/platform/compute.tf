# ---------------------------------------------------------------------------
# Caddy origin target
#
# The origin serves plain HTTP on app_origin_port and only accepts traffic from
# the ALB security group. TLS is terminated at the ALB with the ACM cert. The
# container/runtime bootstrap (Caddy, llm-wiki, Hermes upstreams) is delivered
# by the app repo's compose stack and the downstream runtime issues
# (PLA-249/250/251); this module owns the target + ingress wiring only.
# ---------------------------------------------------------------------------

resource "aws_security_group" "app" {
  name        = "${var.project_name}-origin-sg"
  description = "Caddy origin for the agent.plady.io platform"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-origin-sg"
  }
}

# App ingress is allowed ONLY from the ALB security group.
resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  description                  = "Caddy HTTP from ALB only"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.app_origin_port
  ip_protocol                  = "tcp"
  to_port                      = var.app_origin_port
}

resource "aws_vpc_security_group_ingress_rule" "app_ssh" {
  for_each = toset(var.allowed_ssh_cidr_blocks)

  security_group_id = aws_security_group.app.id
  description       = "SSH"
  cidr_ipv4         = each.value
  from_port         = 22
  ip_protocol       = "tcp"
  to_port           = 22
}

resource "aws_vpc_security_group_egress_rule" "app_all_ipv4" {
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

# Read-only access to the named platform SSM parameters (names only; values are
# injected out of band by the runtime owners).
data "aws_iam_policy_document" "platform_ssm" {
  count = length(local.ssm_parameter_names) > 0 ? 1 : 0

  statement {
    actions   = ["ssm:GetParameter"]
    resources = local.ssm_parameter_arns
  }

  dynamic "statement" {
    for_each = var.ssm_parameter_kms_key_arn != null ? [var.ssm_parameter_kms_key_arn] : []

    content {
      actions   = ["kms:Decrypt"]
      resources = [statement.value]
    }
  }
}

resource "aws_iam_role_policy" "platform_ssm" {
  count = length(local.ssm_parameter_names) > 0 ? 1 : 0

  name   = "${var.project_name}-platform-ssm"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.platform_ssm[0].json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.app.name
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.app.name
  key_name                    = var.key_name

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
    Name = "${var.project_name}-origin"
  }
}
