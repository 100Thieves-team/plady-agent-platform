variable "project_name" {
  description = "Name prefix for AWS resources."
  type        = string
  default     = "plady-agent-platform"
}

variable "environment" {
  description = "Deployment environment placeholder used in SSM parameter paths (dev, staging, prod)."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "CIDR block for the dedicated VPC."
  type        = string
  default     = "10.43.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the public subnets. An ALB requires at least two subnets in two AZs."
  type        = list(string)
  default     = ["10.43.1.0/24", "10.43.2.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) >= 2
    error_message = "public_subnet_cidrs must contain at least two CIDR blocks for ALB high availability."
  }
}

# ---------------------------------------------------------------------------
# DNS / domain
# ---------------------------------------------------------------------------

variable "agent_zone_name" {
  description = "Delegated DNS zone owned by this platform under the Cloudflare-owned plady.io root."
  type        = string
  default     = "agent.plady.io"

  validation {
    condition     = length(trimspace(var.agent_zone_name)) > 0
    error_message = "agent_zone_name must be a non-empty DNS name."
  }
}

variable "manage_dns" {
  description = <<-EOT
    When true, manage the agent.plady.io Route 53 hosted zone, ACM DNS validation records,
    and service alias records in Route 53. Route 53 is currently blocked by an SCP in the
    platform account, so set this to false to apply the ALB/ACM/compute stack and create the
    ACM validation + service CNAME records in Cloudflare instead (see README runbook).
  EOT
  type        = bool
  default     = true
}

variable "service_subdomains" {
  description = "Service hostnames (left labels under agent_zone_name) that resolve to the ALB. Reserved names are still created as alias records."
  type        = list(string)
  default     = ["wiki", "mcp", "hermes"]
}

variable "reserved_subdomains" {
  description = "Reserved service hostnames that resolve to the ALB but return 503 until their runtime is enabled (e.g. n8n by PLA-251)."
  type        = list(string)
  default     = ["n8n"]
}

# ---------------------------------------------------------------------------
# ALB ingress
# ---------------------------------------------------------------------------

variable "allowed_https_cidr_blocks" {
  description = "CIDR blocks allowed to reach the public ALB HTTPS listener."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_http_cidr_blocks" {
  description = "CIDR blocks allowed to reach the public ALB HTTP listener (redirected to HTTPS)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "enable_alb_deletion_protection" {
  description = "Enable deletion protection on the ALB."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# EC2 / Caddy target
# ---------------------------------------------------------------------------

variable "instance_type" {
  description = "EC2 instance type for the Caddy origin target."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Optional existing EC2 key pair name for SSH access. Prefer SSM Session Manager."
  type        = string
  default     = null
}

variable "app_origin_port" {
  description = "HTTP port that Caddy listens on for ALB-to-origin traffic. TLS is terminated at the ALB, so the origin serves plain HTTP."
  type        = number
  default     = 80
}

variable "app_health_check_path" {
  description = "HTTP path the ALB target group uses for origin health checks."
  type        = string
  default     = "/"
}

variable "allowed_ssh_cidr_blocks" {
  description = "CIDR blocks allowed to SSH to the origin instance. Empty disables inbound SSH (prefer SSM)."
  type        = list(string)
  default     = []
}

variable "root_volume_size" {
  description = "Root EBS volume size in GiB."
  type        = number
  default     = 30
}

variable "enable_ssm" {
  description = "Attach AmazonSSMManagedInstanceCore so the instance is reachable with AWS Systems Manager."
  type        = bool
  default     = true
}

variable "container_image_tag" {
  description = "Container image tag that the origin pulls from ECR."
  type        = string
  default     = "latest"
}

# ---------------------------------------------------------------------------
# SSM parameter name contract (names only, never values)
# ---------------------------------------------------------------------------

variable "hermes_api_server_key_ssm_parameter_name" {
  description = "SSM SecureString name for the Hermes API server auth key. Name contract only; value injected by PLA-249."
  type        = string
  default     = null
}

variable "mcp_bearer_token_ssm_parameter_name" {
  description = "SSM SecureString name for the llm-wiki MCP bearer token used to protect mcp.agent.plady.io/mcp."
  type        = string
  default     = null
}

variable "ssm_parameter_kms_key_arn" {
  description = "Optional customer-managed KMS key ARN used to decrypt the SecureString parameters above."
  type        = string
  default     = null
}

# ---------------------------------------------------------------------------
# CI / ECR
# ---------------------------------------------------------------------------

variable "github_actions_repository" {
  description = "GitHub repository allowed to assume the ECR push role, in owner/name form."
  type        = string
  default     = "100Thieves-team/plady-agent-platform"
}

variable "github_actions_oidc_provider_arn" {
  description = "Optional existing GitHub Actions OIDC provider ARN. If null, this module creates one."
  type        = string
  default     = null
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}
