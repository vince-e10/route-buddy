resource "aws_acm_certificate" "demo" {
  domain_name       = var.dns_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate_validation" {
  zone_id = var.route53_hosted_zone_id
  name    = tolist(aws_acm_certificate.demo.domain_validation_options)[0].resource_record_name
  type    = tolist(aws_acm_certificate.demo.domain_validation_options)[0].resource_record_type
  records = [tolist(aws_acm_certificate.demo.domain_validation_options)[0].resource_record_value]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "demo" {
  certificate_arn         = aws_acm_certificate.demo.arn
  validation_record_fqdns = [aws_route53_record.certificate_validation.fqdn]
}

resource "aws_lb" "demo" {
  name                       = local.name_prefix
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = [for subnet in aws_subnet.public : subnet.id]
  ip_address_type            = length(var.ingress_ipv6_cidrs) > 0 ? "dualstack" : "ipv4"
  idle_timeout               = 300
  drop_invalid_header_fields = true

  dynamic "access_logs" {
    for_each = var.alb_log_bucket == "" ? [] : [true]

    content {
      bucket  = var.alb_log_bucket
      prefix  = var.alb_log_prefix
      enabled = true
    }
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name_prefix}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.demo.id

  health_check {
    enabled             = true
    path                = "/healthz"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.demo.arn
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
  load_balancer_arn = aws_lb.demo.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.demo.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_route53_record" "application_ipv4" {
  zone_id = var.route53_hosted_zone_id
  name    = var.dns_name
  type    = "A"

  alias {
    name                   = aws_lb.demo.dns_name
    zone_id                = aws_lb.demo.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "application_ipv6" {
  count = length(var.ingress_ipv6_cidrs) > 0 ? 1 : 0

  zone_id = var.route53_hosted_zone_id
  name    = var.dns_name
  type    = "AAAA"

  alias {
    name                   = aws_lb.demo.dns_name
    zone_id                = aws_lb.demo.zone_id
    evaluate_target_health = true
  }
}
