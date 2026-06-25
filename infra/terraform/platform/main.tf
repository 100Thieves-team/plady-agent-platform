locals {
  common_tags = merge(
    {
      Project   = var.project_name
      ManagedBy = "terraform"
    },
    var.tags,
  )

  # Fully qualified service hostnames under the delegated zone.
  service_fqdns  = { for label in var.service_subdomains : label => "${label}.${var.agent_zone_name}" }
  reserved_fqdns = { for label in var.reserved_subdomains : label => "${label}.${var.agent_zone_name}" }

  # ACM certificate covers the apex of the delegated zone plus a wildcard for all services.
  acm_domain_name              = var.agent_zone_name
  acm_subject_alternative_name = "*.${var.agent_zone_name}"

  ssm_parameter_names = [
    for name in [
      var.hermes_api_server_key_ssm_parameter_name,
      var.mcp_bearer_token_ssm_parameter_name,
    ] : name
    if name != null
  ]

  ssm_parameter_paths = [
    for name in local.ssm_parameter_names :
    startswith(name, "/") ? name : "/${name}"
  ]

  ssm_parameter_arns = [
    for path in local.ssm_parameter_paths :
    "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${path}"
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

# ---------------------------------------------------------------------------
# ECR repositories (prebuilt platform images)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Network: VPC, two public subnets (ALB needs >= 2 AZs), IGW, routing
# ---------------------------------------------------------------------------

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
  count = length(var.public_subnet_cidrs)

  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-${count.index}"
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
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
