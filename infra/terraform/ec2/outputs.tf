output "instance_id" {
  description = "EC2 instance ID."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public IPv4 address of the EC2 instance."
  value       = aws_eip.app.public_ip
}

output "public_dns" {
  description = "Public DNS name of the EC2 instance."
  value       = aws_eip.app.public_dns
}

output "wiki_ui_url" {
  description = "Hugo wiki UI URL."
  value       = "https://${var.domain_name}"
}

output "mcp_http_url" {
  description = "llm-wiki MCP HTTP URL."
  value       = "https://${var.domain_name}/mcp"
}

output "dns_a_record" {
  description = "Create an A record for domain_name pointing to this Elastic IP."
  value       = "${var.domain_name} A ${aws_eip.app.public_ip}"
}

output "ssm_start_session_command" {
  description = "AWS CLI command to open an SSM shell when enable_ssm is true."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.app.id}"
}

output "ecr_registry" {
  description = "ECR registry hostname."
  value       = local.ecr_registry
}

output "ecr_llm_wiki_repository" {
  description = "ECR repository name for the llm-wiki image."
  value       = aws_ecr_repository.llm_wiki.name
}

output "ecr_wiki_ui_repository" {
  description = "ECR repository name for the wiki UI image."
  value       = aws_ecr_repository.wiki_ui.name
}

output "github_actions_ecr_role_arn" {
  description = "IAM role ARN for GitHub Actions OIDC ECR push."
  value       = aws_iam_role.github_actions_ecr.arn
}

output "llm_wiki_image" {
  description = "Full llm-wiki image URI that EC2 pulls."
  value       = local.llm_wiki_image_uri
}

output "wiki_ui_image" {
  description = "Full wiki UI image URI that EC2 pulls."
  value       = local.wiki_ui_image_uri
}
