locals {
  table_names = {
    sessions        = "${local.name_prefix}-sessions"
    trips           = "${local.name_prefix}-trips"
    action_log      = "${local.name_prefix}-action-log"
    pending_actions = "${local.name_prefix}-pending-actions"
  }
}

data "aws_secretsmanager_secret" "application" {
  name = "route-buddy/aws-demo/application"
}

module "data" {
  source = "../modules/data"

  table_names                    = local.table_names
  point_in_time_recovery_enabled = true
  deletion_protection_enabled    = true
  server_side_encryption_enabled = true
}
