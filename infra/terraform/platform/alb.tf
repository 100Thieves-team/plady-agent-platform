# ---------------------------------------------------------------------------
# Public Application Load Balancer
#   - HTTP :80  -> redirect to HTTPS
#   - HTTPS :443 (ACM cert) -> Caddy origin target group (host routing)
#   - reserved hosts (n8n) -> 503 until their runtime is enabled
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-alb-sg"
  description = "Public ingress for the agent.plady.io ALB"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-alb-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  for_each = toset(var.allowed_https_cidr_blocks)

  security_group_id = aws_security_group.alb.id
  description       = "Public HTTPS"
  cidr_ipv4         = each.value
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each = toset(var.allowed_http_cidr_blocks)

  security_group_id = aws_security_group.alb.id
  description       = "Public HTTP (redirected to HTTPS)"
  cidr_ipv4         = each.value
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_origin" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward to Caddy origin"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = var.app_origin_port
  ip_protocol                  = "tcp"
  to_port                      = var.app_origin_port
}

resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = var.enable_alb_deletion_protection

  tags = {
    Name = "${var.project_name}-alb"
  }
}

resource "aws_lb_target_group" "caddy" {
  name        = "${var.project_name}-caddy"
  port        = var.app_origin_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    enabled             = true
    path                = var.app_health_check_path
    protocol            = "HTTP"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }

  tags = {
    Name = "${var.project_name}-caddy"
  }
}

resource "aws_lb_target_group_attachment" "caddy" {
  target_group_arn = aws_lb_target_group.caddy.arn
  target_id        = aws_instance.app.id
  port             = var.app_origin_port
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.agent.arn

  # Live services (wiki/mcp/hermes) are host-routed to the Caddy origin, which
  # does internal host-based routing to the UI/MCP/Hermes upstreams.
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.caddy.arn
  }
}

# Reserved hostnames resolve to the ALB but are not live yet (e.g. n8n -> PLA-251).
resource "aws_lb_listener_rule" "reserved_unavailable" {
  count = length(var.reserved_subdomains) > 0 ? 1 : 0

  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "This endpoint is reserved and not yet live."
      status_code  = "503"
    }
  }

  condition {
    host_header {
      values = [for label in var.reserved_subdomains : "${label}.${var.agent_zone_name}"]
    }
  }
}
