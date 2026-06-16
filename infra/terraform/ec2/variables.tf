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
  description = "Directory on the EC2 instance where you can manually clone the repository."
  type        = string
  default     = "/opt/100thieves-wiki-mcp"
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
