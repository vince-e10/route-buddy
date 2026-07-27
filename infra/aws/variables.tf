variable "aws_account_id" {
  description = "AWS account that would own the simulated demo resources."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "AWS region for the demo."
  type        = string
  default     = "ap-southeast-1"
}

variable "availability_zones" {
  description = "Two distinct availability zones in aws_region."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) == 2 && length(toset(var.availability_zones)) == 2
    error_message = "availability_zones must contain exactly two distinct zones."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR for the demo VPC."
  type        = string
  default     = "10.24.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR."
  }
}

variable "public_subnet_cidrs" {
  description = "IPv4 CIDRs for the two public subnets."
  type        = list(string)

  validation {
    condition     = length(var.public_subnet_cidrs) == 2 && alltrue([for cidr in var.public_subnet_cidrs : can(cidrnetmask(cidr))])
    error_message = "public_subnet_cidrs must contain exactly two valid IPv4 CIDRs."
  }
}

variable "private_subnet_cidrs" {
  description = "IPv4 CIDRs for the two private application subnets."
  type        = list(string)

  validation {
    condition     = length(var.private_subnet_cidrs) == 2 && alltrue([for cidr in var.private_subnet_cidrs : can(cidrnetmask(cidr))])
    error_message = "private_subnet_cidrs must contain exactly two valid IPv4 CIDRs."
  }
}

variable "route53_hosted_zone_id" {
  description = "Route53 hosted zone for dns_name."
  type        = string

  validation {
    condition     = can(regex("^Z[A-Z0-9]+$", var.route53_hosted_zone_id))
    error_message = "route53_hosted_zone_id must be a Route53 hosted zone ID."
  }
}

variable "dns_name" {
  description = "Lowercase DNS name for the demo application."
  type        = string

  validation {
    condition = (
      var.dns_name == lower(var.dns_name) &&
      length(var.dns_name) <= 253 &&
      can(regex("^([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", var.dns_name))
    )
    error_message = "dns_name must be a lowercase DNS name."
  }
}

variable "ingress_ipv4_cidrs" {
  description = "Explicit IPv4 CIDRs allowed to reach the ALB."
  type        = list(string)

  validation {
    condition = (
      length(var.ingress_ipv4_cidrs) > 0 &&
      alltrue([
        for cidr in var.ingress_ipv4_cidrs :
        can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]), 0) > 0
      ])
    )
    error_message = "ingress_ipv4_cidrs must contain valid CIDRs and cannot be empty or world-open."
  }
}

variable "ingress_ipv6_cidrs" {
  description = "Optional explicit IPv6 CIDRs allowed to reach the ALB."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for cidr in var.ingress_ipv6_cidrs :
      can(cidrhost(cidr, 0)) && strcontains(cidr, ":") && try(tonumber(split("/", cidr)[1]), 0) > 0
    ])
    error_message = "ingress_ipv6_cidrs must contain valid IPv6 CIDRs and cannot be world-open."
  }
}

variable "api_image" {
  description = "Digest-pinned ECR image for the API."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be an ECR image pinned by sha256 digest."
  }
}

variable "mock_uber_image" {
  description = "Digest-pinned ECR image for mock-Uber."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.mock_uber_image))
    error_message = "mock_uber_image must be an ECR image pinned by sha256 digest."
  }
}

variable "alb_log_bucket" {
  description = "Existing approved S3 bucket for optional ALB access logs."
  type        = string
  default     = ""
}

variable "alb_log_prefix" {
  description = "Optional key prefix for ALB access logs."
  type        = string
  default     = "route-buddy/aws-demo"
}
