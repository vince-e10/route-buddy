variable "aws_account_id" {
  description = "AWS account that owns the Route Buddy bootstrap resources."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "AWS region for Route Buddy resources."
  type        = string
  default     = "ap-southeast-1"
}

variable "github_oidc_provider_arn" {
  description = "Existing account-level GitHub OIDC provider ARN. Leave null to create it."
  type        = string
  default     = null

  validation {
    condition = (
      var.github_oidc_provider_arn == null ||
      var.github_oidc_provider_arn == "" ||
      var.github_oidc_provider_arn == "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
    )
    error_message = "github_oidc_provider_arn must be the GitHub provider in aws_account_id."
  }
}

variable "route53_hosted_zone_id" {
  description = "Hosted zone the demo deploy role may update. Leave null until the demo zone is selected."
  type        = string
  default     = null

  validation {
    condition = (
      var.route53_hosted_zone_id == null ||
      var.route53_hosted_zone_id == "" ||
      can(regex("^Z[A-Z0-9]+$", var.route53_hosted_zone_id))
    )
    error_message = "route53_hosted_zone_id must be a Route53 hosted zone ID."
  }
}
