output "table_names" {
  value = {
    sessions        = aws_dynamodb_table.sessions.name
    trips           = aws_dynamodb_table.trips.name
    action_log      = aws_dynamodb_table.action_log.name
    pending_actions = aws_dynamodb_table.pending_actions.name
  }
}

output "all_protections_enabled" {
  value = alltrue([
    aws_dynamodb_table.sessions.deletion_protection_enabled &&
    aws_dynamodb_table.sessions.point_in_time_recovery[0].enabled &&
    aws_dynamodb_table.sessions.server_side_encryption[0].enabled,
    aws_dynamodb_table.trips.deletion_protection_enabled &&
    aws_dynamodb_table.trips.point_in_time_recovery[0].enabled &&
    aws_dynamodb_table.trips.server_side_encryption[0].enabled,
    aws_dynamodb_table.action_log.deletion_protection_enabled &&
    aws_dynamodb_table.action_log.point_in_time_recovery[0].enabled &&
    aws_dynamodb_table.action_log.server_side_encryption[0].enabled,
    aws_dynamodb_table.pending_actions.deletion_protection_enabled &&
    aws_dynamodb_table.pending_actions.point_in_time_recovery[0].enabled &&
    aws_dynamodb_table.pending_actions.server_side_encryption[0].enabled,
  ])
}
