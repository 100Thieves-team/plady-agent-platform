# ---------------------------------------------------------------------------
# Delegated Route 53 hosted zone for agent.plady.io
#
# plady.io is owned and managed in Cloudflare. This module owns only the
# delegated agent.plady.io zone. After apply, hand agent_zone_name_servers off
# to PLA-248 to create the NS delegation in the Cloudflare root zone.
#
# Route 53 is currently blocked by an SCP in the platform account. Set
# manage_dns = false to skip every Route 53 resource here and instead create the
# ACM validation CNAME and service CNAME records in Cloudflare (see README).
# ---------------------------------------------------------------------------

resource "aws_route53_zone" "agent" {
  count = var.manage_dns ? 1 : 0

  name    = var.agent_zone_name
  comment = "Delegated platform zone for ${var.agent_zone_name} (root plady.io stays in Cloudflare)"

  tags = {
    Name = var.agent_zone_name
  }
}

# ACM DNS validation records.
resource "aws_route53_record" "acm_validation" {
  for_each = var.manage_dns ? local.acm_validation_options : {}

  zone_id         = aws_route53_zone.agent[0].zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

# Service + reserved alias records -> ALB.
resource "aws_route53_record" "service_alias" {
  for_each = var.manage_dns ? merge(local.service_fqdns, local.reserved_fqdns) : {}

  zone_id = aws_route53_zone.agent[0].zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
