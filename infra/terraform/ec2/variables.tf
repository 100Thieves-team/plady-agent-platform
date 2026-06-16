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
  description = "EC2 instance type. t3.large is the default because the first Docker build compiles Rust."
  type        = string
  default     = "t3.large"
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

variable "app_dir" {
  description = "Directory on the EC2 instance where the repository is cloned or where you can manually clone it."
  type        = string
  default     = "/opt/100thieves-wiki-mcp"
}

variable "repository_url" {
  description = "HTTPS Git repository URL used when github_token_ssm_parameter_name is set."
  type        = string
  default     = "https://github.com/100Thieves-team/100Thieves-wiki-mcp.git"
}

variable "repository_ref" {
  description = "Branch or tag to clone when github_token_ssm_parameter_name is set."
  type        = string
  default     = "main"
}

variable "github_token_ssm_parameter_name" {
  description = "Optional SSM Parameter Store SecureString name containing a GitHub token. When set, EC2 auto-clones repository_url."
  type        = string
  default     = null

  validation {
    condition     = var.github_token_ssm_parameter_name == null || length(trimspace(var.github_token_ssm_parameter_name)) > 0
    error_message = "github_token_ssm_parameter_name must be null or a non-empty SSM parameter name."
  }
}

variable "github_token_kms_key_arn" {
  description = "Optional KMS key ARN if the GitHub token SecureString uses a customer-managed KMS key."
  type        = string
  default     = null

  validation {
    condition     = var.github_token_kms_key_arn == null || length(trimspace(var.github_token_kms_key_arn)) > 0
    error_message = "github_token_kms_key_arn must be null or a non-empty KMS key ARN."
  }
}

variable "docker_compose_version" {
  description = "Docker Compose plugin version installed by cloud-init."
  type        = string
  default     = "2.39.4"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GiB."
  type        = number
  default     = 80
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
