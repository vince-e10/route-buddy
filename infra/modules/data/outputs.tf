output "table_names" {
  value = {
    sessions        = aws_dynamodb_table.sessions.name
    trips           = aws_dynamodb_table.trips.name
    action_log      = aws_dynamodb_table.action_log.name
    pending_actions = aws_dynamodb_table.pending_actions.name
  }
}
