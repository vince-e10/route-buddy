provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

locals {
  project                    = "route-buddy"
  repository                 = "vince-e10/route-buddy"
  state_bucket_name          = "${local.project}-tfstate-${var.aws_account_id}-${var.aws_region}"
  demo_state_key             = "environments/aws-demo/terraform.tfstate"
  application_secret_name    = "route-buddy/aws-demo/application"
  bootstrap_role_name        = "${local.project}-bootstrap"
  demo_deploy_role_name      = "${local.project}-aws-demo-deploy"
  adopt_github_oidc_provider = var.github_oidc_provider_arn != null && var.github_oidc_provider_arn != ""
  github_oidc_provider_arn   = local.adopt_github_oidc_provider ? data.aws_iam_openid_connect_provider.github[0].arn : aws_iam_openid_connect_provider.github[0].arn
  manage_route53_zone        = var.route53_hosted_zone_id != null && var.route53_hosted_zone_id != ""
  ecr_repository_names       = toset(["${local.project}/api", "${local.project}/mock-uber"])
  ecr_repository_arns        = [for name in local.ecr_repository_names : "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/${name}"]
  application_role_arns      = [for name in ["execution", "task"] : "arn:aws:iam::${var.aws_account_id}:role/${local.project}-aws-demo-${name}"]
  application_role_arn_glob  = "arn:aws:iam::${var.aws_account_id}:role/${local.project}-aws-demo-*"
  runtime_boundary_names = {
    execution = "${local.project}-aws-demo-execution-boundary"
    task      = "${local.project}-aws-demo-task-boundary"
  }
  runtime_boundary_arns = {
    for role, name in local.runtime_boundary_names :
    role => "arn:aws:iam::${var.aws_account_id}:policy/${name}"
  }
  bootstrap_role_arn        = "arn:aws:iam::${var.aws_account_id}:role/${local.bootstrap_role_name}"
  demo_deploy_role_arn      = "arn:aws:iam::${var.aws_account_id}:role/${local.demo_deploy_role_name}"
  state_bucket_arn          = "arn:aws:s3:::${local.state_bucket_name}"
  github_oidc_provider_path = "token.actions.githubusercontent.com"
  application_resource_tags = {
    Project     = local.project
    Environment = "aws-demo"
  }
  tags = {
    Project    = local.project
    ManagedBy  = "terraform"
    Repository = local.repository
  }
}

resource "aws_secretsmanager_secret" "application" {
  name                    = local.application_secret_name
  recovery_window_in_days = 7
}
