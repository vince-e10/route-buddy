locals {
  project     = "route-buddy"
  environment = "aws-demo"
  repository  = "vince-e10/route-buddy"
  name_prefix = "${local.project}-${local.environment}"
  tags = {
    project     = local.project
    environment = local.environment
    managed-by  = "terraform"
    repository  = local.repository
  }
}
