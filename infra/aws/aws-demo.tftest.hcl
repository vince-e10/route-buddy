mock_provider "aws" {}

variables {
  aws_account_id         = "000000000000"
  availability_zones     = ["ap-southeast-1a", "ap-southeast-1b"]
  public_subnet_cidrs    = ["10.24.0.0/24", "10.24.1.0/24"]
  private_subnet_cidrs   = ["10.24.10.0/24", "10.24.11.0/24"]
  route53_hosted_zone_id = "Z0000000000000"
  dns_name               = "route-buddy.example.com"
  ingress_ipv4_cidrs     = ["203.0.113.0/24"]
  api_image              = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  mock_uber_image        = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/mock-uber@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

override_resource {
  target = aws_acm_certificate.demo
  values = {
    arn = "arn:aws:acm:ap-southeast-1:000000000000:certificate/mock"
    domain_validation_options = [
      {
        domain_name           = "route-buddy.example.com"
        resource_record_name  = "_mock.route-buddy.example.com"
        resource_record_type  = "CNAME"
        resource_record_value = "_mock.acm-validations.aws"
      },
    ]
  }
}

override_resource {
  target = aws_vpc.demo
  values = {
    id              = "vpc-00000000000000000"
    ipv6_cidr_block = "2001:db8:100::/56"
  }
}

override_resource {
  target = aws_acm_certificate_validation.demo
  values = {
    certificate_arn = "arn:aws:acm:ap-southeast-1:000000000000:certificate/mock"
  }
}

override_resource {
  target = aws_iam_role.execution
  values = {
    id  = "route-buddy-aws-demo-execution"
    arn = "arn:aws:iam::000000000000:role/route-buddy-aws-demo-execution"
  }
}

override_resource {
  target = aws_iam_role.task
  values = {
    id  = "route-buddy-aws-demo-task"
    arn = "arn:aws:iam::000000000000:role/route-buddy-aws-demo-task"
  }
}

override_resource {
  target = aws_lb.demo
  values = {
    id       = "arn:aws:elasticloadbalancing:ap-southeast-1:000000000000:loadbalancer/app/route-buddy-aws-demo/0000000000000000"
    arn      = "arn:aws:elasticloadbalancing:ap-southeast-1:000000000000:loadbalancer/app/route-buddy-aws-demo/0000000000000000"
    dns_name = "route-buddy-aws-demo.ap-southeast-1.elb.amazonaws.com"
    zone_id  = "Z0000000000000"
  }
}

override_resource {
  target = aws_lb_target_group.api
  values = {
    arn = "arn:aws:elasticloadbalancing:ap-southeast-1:000000000000:targetgroup/route-buddy-aws-demo-api/0000000000000000"
  }
}

override_resource {
  target = aws_ecs_cluster.demo
  values = {
    id   = "arn:aws:ecs:ap-southeast-1:000000000000:cluster/route-buddy-aws-demo"
    name = "route-buddy-aws-demo"
  }
}

override_resource {
  target = aws_ecs_task_definition.demo
  values = {
    arn = "arn:aws:ecs:ap-southeast-1:000000000000:task-definition/route-buddy-aws-demo:1"
  }
}

override_resource {
  target = aws_secretsmanager_secret.application
  values = {
    name = "route-buddy/aws-demo/application"
    arn  = "arn:aws:secretsmanager:ap-southeast-1:000000000000:secret:route-buddy/aws-demo/application-mock"
  }
}

run "demo_shape" {
  command = apply

  assert {
    condition     = output.application_url == "https://route-buddy.example.com"
    error_message = "The application URL must use the configured HTTPS DNS name."
  }

  assert {
    condition = (
      length(aws_subnet.public) == 2 &&
      length(aws_subnet.private) == 2 &&
      length(aws_route_table.private) == 2 &&
      length(aws_vpc_endpoint.dynamodb.route_table_ids) == 2
    )
    error_message = "The VPC must span two public and two private subnets with DynamoDB routes."
  }

  assert {
    condition = (
      aws_lb.demo.internal == false &&
      aws_lb.demo.idle_timeout == 300 &&
      aws_lb_target_group.api.port == 8000 &&
      aws_lb_target_group.api.health_check[0].path == "/healthz"
    )
    error_message = "The public ALB must terminate the API's HTTPS and WebSocket traffic."
  }

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.task_api.from_port == 8000 &&
      aws_vpc_security_group_ingress_rule.task_api.referenced_security_group_id == aws_security_group.alb.id
    )
    error_message = "Only the ALB security group may reach the API task on port 8000."
  }

  assert {
    condition = (
      aws_ecs_service.demo.desired_count == 1 &&
      aws_ecs_service.demo.network_configuration[0].assign_public_ip == false &&
      aws_ecs_service.demo.deployment_circuit_breaker[0].enable &&
      aws_ecs_service.demo.deployment_circuit_breaker[0].rollback
    )
    error_message = "The Fargate service must remain one private task with rollback enabled."
  }

  assert {
    condition = (
      module.data.table_names.sessions == "route-buddy-aws-demo-sessions" &&
      module.data.table_names.trips == "route-buddy-aws-demo-trips" &&
      module.data.table_names.action_log == "route-buddy-aws-demo-action-log" &&
      module.data.table_names.pending_actions == "route-buddy-aws-demo-pending-actions"
    )
    error_message = "The reused data module must own four environment-prefixed tables."
  }

  assert {
    condition = (
      length(jsondecode(aws_ecs_task_definition.demo.container_definitions)) == 2 &&
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "api"
      ]).image == var.api_image &&
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "mock-uber"
      ]).image == var.mock_uber_image
    )
    error_message = "The task must contain only the two digest-pinned application containers."
  }

  assert {
    condition = (
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "api"
      ]).readonlyRootFilesystem &&
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "mock-uber"
      ]).readonlyRootFilesystem &&
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "api"
      ]).user == "app" &&
      one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "mock-uber"
      ]).user == "app" &&
      !can(one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "mock-uber"
      ]).portMappings)
    )
    error_message = "Both containers must be read-only and mock-Uber must expose no task port."
  }

  assert {
    condition = (
      one([
        for item in one([
          for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
          container if container.name == "api"
        ]).environment : item.value if item.name == "UBER_BASE_URL"
      ]) == "http://localhost:8001" &&
      one([
        for item in one([
          for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
          container if container.name == "mock-uber"
        ]).environment : item.value if item.name == "WEBHOOK_TARGET_URL"
      ]) == "http://localhost:8000/webhooks/uber"
    )
    error_message = "Same-task API and mock-Uber communication must use localhost."
  }

  assert {
    condition = toset([
      for item in one([
        for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
        container if container.name == "api"
      ]).environment : "${item.name}=${item.value}"
      if contains([
        "SESSIONS_TABLE",
        "TRIPS_TABLE",
        "ACTION_LOG_TABLE",
        "PENDING_ACTIONS_TABLE",
      ], item.name)
      ]) == toset([
      "SESSIONS_TABLE=route-buddy-aws-demo-sessions",
      "TRIPS_TABLE=route-buddy-aws-demo-trips",
      "ACTION_LOG_TABLE=route-buddy-aws-demo-action-log",
      "PENDING_ACTIONS_TABLE=route-buddy-aws-demo-pending-actions",
    ])
    error_message = "The API must receive the exact data-module table names."
  }

  assert {
    condition = length(setintersection(
      toset([
        for item in one([
          for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
          container if container.name == "api"
        ]).environment : item.name
      ]),
      toset([
        "AWS_ENDPOINT_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "FLOCI_STORAGE_MODE",
        "FLOCI_STORAGE_PERSISTENT_PATH",
      ]),
    )) == 0
    error_message = "The AWS task definition must omit local emulator settings and AWS keys."
  }

  assert {
    condition = (
      toset([
        for item in one([
          for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
          container if container.name == "api"
        ]).secrets : item.name
        ]) == toset([
        "OPENROUTER_API_KEY",
        "WEBHOOK_SHARED_SECRET",
        "ONEMAP_EMAIL",
        "ONEMAP_PASSWORD",
        "RIDER_FIRST_NAME",
        "RIDER_LAST_NAME",
        "RIDER_PHONE",
      ]) &&
      alltrue([
        for item in one([
          for container in jsondecode(aws_ecs_task_definition.demo.container_definitions) :
          container if container.name == "api"
        ]).secrets : startswith(item.valueFrom, aws_secretsmanager_secret.application.arn)
      ])
    )
    error_message = "The API must inject only the exact seven JSON secret keys."
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.api.retention_in_days == 30 &&
      aws_cloudwatch_log_group.mock_uber.retention_in_days == 30
    )
    error_message = "Both application log groups must retain logs for 30 days."
  }

  assert {
    condition = alltrue([
      for resource in jsondecode(aws_iam_role_policy.task.policy).Statement[0].Resource :
      !strcontains(resource, "*")
    ])
    error_message = "The task role must not use wildcard DynamoDB resources."
  }

  assert {
    condition = (
      length(jsondecode(aws_iam_role_policy.task.policy).Statement[0].Resource) == 5 &&
      contains(
        jsondecode(aws_iam_role_policy.task.policy).Statement[0].Resource,
        "arn:aws:dynamodb:ap-southeast-1:000000000000:table/route-buddy-aws-demo-trips/index/by_session",
      )
    )
    error_message = "The task role must cover exactly four tables and the trips by_session index."
  }

  assert {
    condition = one([
      for statement in jsondecode(aws_iam_role_policy.execution.policy).Statement :
      statement.Resource if statement.Sid == "InjectApplicationSecret"
    ]) == aws_secretsmanager_secret.application.arn
    error_message = "Only the execution role may read the one application secret."
  }
}

run "reject_empty_ipv4_ingress" {
  command = plan

  variables {
    ingress_ipv4_cidrs = []
  }

  expect_failures = [var.ingress_ipv4_cidrs]
}

run "reject_world_open_ingress" {
  command = plan

  variables {
    ingress_ipv4_cidrs = ["0.0.0.0/00"]
    ingress_ipv6_cidrs = ["0000::/0"]
  }

  expect_failures = [var.ingress_ipv4_cidrs, var.ingress_ipv6_cidrs]
}

run "reject_tagged_images" {
  command = plan

  variables {
    api_image       = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/api:latest"
    mock_uber_image = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/mock-uber:latest"
  }

  expect_failures = [var.api_image, var.mock_uber_image]
}

run "reject_uppercase_dns" {
  command = plan

  variables {
    dns_name = "Route-Buddy.example.com"
  }

  expect_failures = [var.dns_name]
}

run "reject_malformed_dns" {
  command = plan

  variables {
    dns_name = "route-buddy..example.com"
  }

  expect_failures = [var.dns_name]
}

run "enable_optional_ipv6_ingress" {
  command = plan

  variables {
    ingress_ipv6_cidrs = ["2001:db8::/64"]
  }

  assert {
    condition = (
      aws_lb.demo.ip_address_type == "dualstack" &&
      length(aws_vpc_security_group_ingress_rule.alb_https_ipv6) == 1
    )
    error_message = "Configured IPv6 ingress must use a dual-stack ALB and an explicit rule."
  }
}

run "enable_optional_access_logs" {
  command = plan

  variables {
    alb_log_bucket = "approved-existing-alb-log-bucket"
  }

  assert {
    condition = (
      aws_lb.demo.access_logs[0].enabled &&
      aws_lb.demo.access_logs[0].bucket == "approved-existing-alb-log-bucket"
    )
    error_message = "ALB logging must use only the supplied existing bucket."
  }
}
