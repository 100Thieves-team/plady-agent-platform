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

variable "app_repository_url" {
  description = "SSH Git repository URL for this app repo. Use the github.com-llm-wiki-app host alias when using the deploy-key bootstrap."
  type        = string
  default     = "git@github.com-llm-wiki-app:100Thieves-team/100Thieves-wiki-mcp.git"
}

variable "app_repository_ref" {
  description = "Branch or tag to clone when app_repo_ssh_key_ssm_parameter_name is set."
  type        = string
  default     = "main"
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
