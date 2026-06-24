variable "project_name" {
  description = "Name prefix for AWS resources."
  type        = string
  default     = "100thieves-wiki"
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-northeast-2"
}

variable "availability_zone" {
  description = "Optional availability zone. If null, the first available AZ in aws_region is used."
  type        = string
  default     = null
}

variable "vpc_cidr" {
  description = "CIDR block for the dedicated VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet."
  type        = string
  default     = "10.42.1.0/24"
}

variable "instance_type" {
  description = "EC2 instance type. Default is t3.micro for free-tier constrained accounts; use t3.small if your account allows it."
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "Optional existing EC2 key pair name for SSH access. Prefer SSM when possible."
  type        = string
  default     = null
}

variable "allowed_ui_cidr_blocks" {
  description = "CIDR blocks allowed to access the Hugo wiki UI."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_mcp_cidr_blocks" {
  description = "CIDR blocks allowed to access the MCP HTTP endpoint. Keep this restricted."
  type        = list(string)
  default     = []
}

variable "allowed_http_cidr_blocks" {
  description = "CIDR blocks allowed to access Caddy HTTP for Let's Encrypt HTTP-01 and HTTP to HTTPS redirects."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_https_cidr_blocks" {
  description = "CIDR blocks allowed to access Caddy HTTPS."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "allowed_ssh_cidr_blocks" {
  description = "CIDR blocks allowed to SSH to the instance. Empty disables inbound SSH."
  type        = list(string)
  default     = []
}

variable "wiki_ui_port" {
  description = "Host port exposed by docker compose for the Hugo UI."
  type        = number
  default     = 1313
}

variable "mcp_port" {
  description = "Host port exposed by docker compose for llm-wiki MCP HTTP."
  type        = number
  default     = 18765
}

variable "domain_name" {
  description = "Public DNS name served by Caddy with automatic HTTPS."
  type        = string
  default     = "plady.kro.kr"

  validation {
    condition     = length(trimspace(var.domain_name)) > 0
    error_message = "domain_name must be a non-empty DNS name."
  }
}

variable "acme_email" {
  description = "Contact email for the Caddy ACME account. Caddy uses ZeroSSL as the primary ACME CA for this deployment."
  type        = string
  default     = "admin@plady.kro.kr"

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.acme_email))
    error_message = "acme_email must be a valid email address."
  }
}

variable "app_dir" {
  description = "Directory on the EC2 instance where the repository is cloned or where you can manually clone it."
  type        = string
  default     = "/opt/plady-agent-platform"
}

variable "app_repository_url" {
  description = "SSH Git repository URL for this app repo. Use the github.com-llm-wiki-app host alias when using the deploy-key bootstrap."
  type        = string
  default     = "git@github.com-llm-wiki-app:100Thieves-team/plady-agent-platform.git"
}

variable "app_repository_ref" {
  description = "Branch or tag to clone when app_repo_ssh_key_ssm_parameter_name is set."
  type        = string
  default     = "main"
}

variable "container_image_tag" {
  description = "Container image tag that EC2 pulls from ECR."
  type        = string
  default     = "latest"
}

variable "app_repo_ssh_key_ssm_parameter_name" {
  description = "Optional SSM Parameter Store SecureString name containing the read-only SSH deploy private key for this app repo. When set, EC2 auto-clones app_repository_url."
  type        = string
  default     = null

  validation {
    condition     = var.app_repo_ssh_key_ssm_parameter_name == null ? true : length(trimspace(var.app_repo_ssh_key_ssm_parameter_name)) > 0
    error_message = "app_repo_ssh_key_ssm_parameter_name must be null or a non-empty SSM parameter name."
  }
}

variable "app_repo_ssh_key_kms_key_arn" {
  description = "Optional KMS key ARN if the app repo SSH key SecureString uses a customer-managed KMS key."
  type        = string
  default     = null

  validation {
    condition     = var.app_repo_ssh_key_kms_key_arn == null ? true : length(trimspace(var.app_repo_ssh_key_kms_key_arn)) > 0
    error_message = "app_repo_ssh_key_kms_key_arn must be null or a non-empty KMS key ARN."
  }
}

variable "wiki_data_repository_url" {
  description = "Optional SSH Git repository URL for the separate wiki data repo. Use the github.com-llm-wiki-data host alias when using a deploy key."
  type        = string
  default     = "git@github.com-llm-wiki-data:100Thieves-team/team-wiki-v2.git"
}

variable "wiki_data_repo_ssh_key_ssm_parameter_name" {
  description = "Optional SSM Parameter Store SecureString name containing the SSH deploy private key for the wiki data repo. Set this with wiki_data_repository_url to clone existing wiki data."
  type        = string
  default     = null

  validation {
    condition     = var.wiki_data_repo_ssh_key_ssm_parameter_name == null ? true : length(trimspace(var.wiki_data_repo_ssh_key_ssm_parameter_name)) > 0
    error_message = "wiki_data_repo_ssh_key_ssm_parameter_name must be null or a non-empty SSM parameter name."
  }
}

variable "wiki_data_repo_ssh_key_kms_key_arn" {
  description = "Optional KMS key ARN if the wiki data repo SSH key SecureString uses a customer-managed KMS key."
  type        = string
  default     = null

  validation {
    condition     = var.wiki_data_repo_ssh_key_kms_key_arn == null ? true : length(trimspace(var.wiki_data_repo_ssh_key_kms_key_arn)) > 0
    error_message = "wiki_data_repo_ssh_key_kms_key_arn must be null or a non-empty KMS key ARN."
  }
}


variable "mcp_bearer_token_ssm_parameter_name" {
  description = "Optional SSM Parameter Store SecureString name containing the bearer token required by the MCP reverse proxy. Set this before exposing MCP publicly."
  type        = string
  default     = null

  validation {
    condition     = var.mcp_bearer_token_ssm_parameter_name == null ? true : length(trimspace(var.mcp_bearer_token_ssm_parameter_name)) > 0
    error_message = "mcp_bearer_token_ssm_parameter_name must be null or a non-empty SSM parameter name."
  }
}

variable "mcp_bearer_token_kms_key_arn" {
  description = "Optional KMS key ARN if the MCP bearer token SecureString uses a customer-managed KMS key."
  type        = string
  default     = null

  validation {
    condition     = var.mcp_bearer_token_kms_key_arn == null ? true : length(trimspace(var.mcp_bearer_token_kms_key_arn)) > 0
    error_message = "mcp_bearer_token_kms_key_arn must be null or a non-empty KMS key ARN."
  }
}

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

variable "docker_compose_version" {
  description = "Docker Compose plugin version installed by cloud-init."
  type        = string
  default     = "2.39.4"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GiB."
  type        = number
  default     = 30
}

variable "enable_ssm" {
  description = "Attach AmazonSSMManagedInstanceCore so the instance can be accessed with AWS Systems Manager."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}
