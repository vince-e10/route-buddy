output "application_url" {
  value = "https://${var.dns_name}"
}

output "alb_arn" {
  value = aws_lb.demo.arn
}

output "target_group_arn" {
  value = aws_lb_target_group.api.arn
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.demo.name
}

output "ecs_service_name" {
  value = aws_ecs_service.demo.name
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.demo.arn
}

output "table_names" {
  value = module.data.table_names
}

output "secret_arn" {
  value = data.aws_secretsmanager_secret.application.arn
}

output "log_group_names" {
  value = {
    api       = aws_cloudwatch_log_group.api.name
    mock_uber = aws_cloudwatch_log_group.mock_uber.name
  }
}
