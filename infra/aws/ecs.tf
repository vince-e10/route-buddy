locals {
  log_groups = {
    api       = "/route-buddy/aws-demo/api"
    mock_uber = "/route-buddy/aws-demo/mock-uber"
  }
  api_environment = [
    { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    { name = "LLM_MODE", value = "openrouter" },
    { name = "OPENROUTER_BASE_URL", value = "https://openrouter.ai/api/v1" },
    { name = "OPENROUTER_MODEL_PRIMARY", value = "z-ai/glm-4.5-air" },
    { name = "OPENROUTER_MODEL_FALLBACK", value = "minimax/minimax-m2" },
    { name = "UBER_BASE_URL", value = "http://localhost:8001" },
    { name = "UBER_API_TOKEN", value = "mock-token" },
    { name = "UBER_ORG_UUID", value = "mock-org-uuid" },
    { name = "ONEMAP_BASE_URL", value = "https://www.onemap.gov.sg" },
    { name = "SESSIONS_TABLE", value = module.data.table_names.sessions },
    { name = "TRIPS_TABLE", value = module.data.table_names.trips },
    { name = "ACTION_LOG_TABLE", value = module.data.table_names.action_log },
    { name = "PENDING_ACTIONS_TABLE", value = module.data.table_names.pending_actions },
  ]
  secret_keys = toset([
    "OPENROUTER_API_KEY",
    "WEBHOOK_SHARED_SECRET",
    "ONEMAP_EMAIL",
    "ONEMAP_PASSWORD",
    "RIDER_FIRST_NAME",
    "RIDER_LAST_NAME",
    "RIDER_PHONE",
  ])
}

resource "aws_cloudwatch_log_group" "api" {
  name              = local.log_groups.api
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "mock_uber" {
  name              = local.log_groups.mock_uber
  retention_in_days = 30
}

resource "aws_ecs_cluster" "demo" {
  name = local.name_prefix
}

resource "aws_ecs_task_definition" "demo" {
  family                   = local.name_prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  lifecycle {
    create_before_destroy = true
  }

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name                   = "mock-uber"
      image                  = var.mock_uber_image
      essential              = true
      user                   = "app"
      readonlyRootFilesystem = true
      environment = [
        { name = "SIM_SPEED", value = "1.0" },
        { name = "MOCK_DETERMINISTIC", value = "0" },
        { name = "UBER_ORG_UUID", value = "mock-org-uuid" },
        { name = "WEBHOOK_TARGET_URL", value = "http://localhost:8000/webhooks/uber" },
      ]
      secrets = [{
        name      = "WEBHOOK_SHARED_SECRET"
        valueFrom = "${data.aws_secretsmanager_secret.application.arn}:WEBHOOK_SHARED_SECRET::"
      }]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"from urllib.request import urlopen; urlopen('http://localhost:8001/healthz')\"",
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.mock_uber.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "mock-uber"
        }
      }
    },
    {
      name                   = "api"
      image                  = var.api_image
      essential              = true
      user                   = "app"
      readonlyRootFilesystem = true
      dependsOn = [{
        containerName = "mock-uber"
        condition     = "HEALTHY"
      }]
      portMappings = [{
        name          = "api"
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
      }]
      environment = local.api_environment
      secrets = [
        for key in local.secret_keys : {
          name      = key
          valueFrom = "${data.aws_secretsmanager_secret.application.arn}:${key}::"
        }
      ]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"from urllib.request import urlopen; urlopen('http://localhost:8000/healthz')\"",
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
    },
  ])
}

resource "aws_ecs_service" "demo" {
  name                              = local.name_prefix
  cluster                           = aws_ecs_cluster.demo.id
  task_definition                   = aws_ecs_task_definition.demo.arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  platform_version                  = "1.4.0"
  health_check_grace_period_seconds = 60
  wait_for_steady_state             = true
  enable_execute_command            = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = [for subnet in aws_subnet.private : subnet.id]
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
}
