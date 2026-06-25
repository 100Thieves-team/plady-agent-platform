# ---------------------------------------------------------------------------
# ACM certificate for agent.plady.io + *.agent.plady.io (DNS validation)
#
# The certificate request itself does not require Route 53. Only the automatic
# validation-record creation and the validation wait depend on a writable DNS
# zone. When manage_dns = false (Route 53 SCP block), the validation CNAMEs are
# surfaced as outputs to be created in Cloudflare under agent.plady.io instead.
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "agent" {
  domain_name               = local.acm_domain_name
  subject_alternative_names = [local.acm_subject_alternative_name]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name = "${var.project_name}-cert"
  }
}

# Distinct validation options keyed by domain (apex + wildcard often share one).
locals {
  acm_validation_options = {
    for dvo in aws_acm_certificate.agent.domain_validation_options :
    dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }
}

# Block until issued only when Route 53 manages (and can satisfy) validation.
resource "aws_acm_certificate_validation" "agent" {
  count = var.manage_dns ? 1 : 0

  certificate_arn         = aws_acm_certificate.agent.arn
  validation_record_fqdns = [for record in aws_route53_record.acm_validation : record.fqdn]
}
