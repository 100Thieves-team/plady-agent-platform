output "instance_id" {
  description = "EC2 instance ID."
  value       = aws_instance.app.id
}

output "public_ip" {
  description = "Public IPv4 address of the EC2 instance."
  value       = aws_instance.app.public_ip
}

output "public_dns" {
  description = "Public DNS name of the EC2 instance."
  value       = aws_instance.app.public_dns
}

output "wiki_ui_url" {
  description = "Hugo wiki UI URL."
  value       = "http://${aws_instance.app.public_ip}:${var.wiki_ui_port}"
}

output "mcp_http_url" {
  description = "llm-wiki MCP HTTP URL."
  value       = "http://${aws_instance.app.public_ip}:${var.mcp_port}/mcp"
}

output "ssm_start_session_command" {
  description = "AWS CLI command to open an SSM shell when enable_ssm is true."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.app.id}"
}
