# ---------------------------------------------------------------------------
# DNS delegation
# ---------------------------------------------------------------------------

output "agent_zone_name_servers" {
  description = "Name servers for the delegated agent.plady.io Route 53 zone. Hand these to PLA-248 to create the NS delegation in the Cloudflare plady.io root. Empty when manage_dns = false (Route 53 SCP block)."
  value       = var.manage_dns ? aws_route53_zone.agent[0].name_servers : []
}

output "agent_zone_id" {
  description = "Route 53 hosted zone ID for agent.plady.io. Null when manage_dns = false."
  value       = var.manage_dns ? aws_route53_zone.agent[0].zone_id : null
}

# ---------------------------------------------------------------------------
# ACM
# ---------------------------------------------------------------------------

output "acm_certificate_arn" {
  description = "ACM certificate ARN for agent.plady.io and *.agent.plady.io."
  value       = aws_acm_certificate.agent.arn
}

output "acm_validation_records" {
  description = "DNS validation records to create when manage_dns = false. Add these CNAMEs in Cloudflare under agent.plady.io so ACM can issue the certificate."
  value = {
    for domain, opt in local.acm_validation_options : domain => {
      name  = opt.name
      type  = opt.type
      value = opt.record
    }
  }
}

# ---------------------------------------------------------------------------
# ALB
# ---------------------------------------------------------------------------

output "alb_dns_name" {
  description = "Public DNS name of the ALB. Point service hostnames at this (Route 53 alias when managed, Cloudflare CNAME otherwise)."
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "Canonical hosted zone ID of the ALB (for Route 53 alias records)."
  value       = aws_lb.main.zone_id
}

output "cloudflare_service_records" {
  description = "CNAME records to create in Cloudflare under agent.plady.io when manage_dns = false. Each service/reserved hostname should CNAME to the ALB DNS name."
  value = {
    for label, fqdn in merge(local.service_fqdns, local.reserved_fqdns) :
    fqdn => aws_lb.main.dns_name
  }
}

# ---------------------------------------------------------------------------
# Public endpoint contract (platform-contract.md)
# ---------------------------------------------------------------------------

output "wiki_url" {
  description = "Canonical wiki UI URL."
  value       = "https://wiki.${var.agent_zone_name}"
}

output "mcp_url" {
  description = "llm-wiki MCP HTTP endpoint (bearer-token protected)."
  value       = "https://mcp.${var.agent_zone_name}/mcp"
}

# PLA-244 Slack/Hermes handoff URLs.
output "hermes_public_origin_url" {
  description = "PLA-244 handoff: Hermes Gateway public origin for Slack event/interactivity/OAuth paths."
  value       = "https://hermes.${var.agent_zone_name}"
}

output "hermes_openai_base_url" {
  description = "PLA-244 handoff: OpenAI-compatible Hermes base URL for client configuration."
  value       = "https://hermes.${var.agent_zone_name}/v1"
}

# ---------------------------------------------------------------------------
# ECR / CI / compute
# ---------------------------------------------------------------------------

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

output "origin_instance_id" {
  description = "EC2 instance ID of the Caddy origin."
  value       = aws_instance.app.id
}

output "ssm_start_session_command" {
  description = "AWS CLI command to open an SSM shell on the origin when enable_ssm is true."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.app.id}"
}
