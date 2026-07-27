locals {
  execution_role_name = "${local.name_prefix}-execution"
  task_role_name      = "${local.name_prefix}-task"
  ecr_repository_arns = [
    "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/route-buddy/api",
    "arn:aws:ecr:${var.aws_region}:${var.aws_account_id}:repository/route-buddy/mock-uber",
  ]
  table_arns = {
    for key, name in local.table_names :
    key => "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${name}"
  }
  task_trust_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
  execution_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuthorization"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "PullImages"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = local.ecr_repository_arns
      },
      {
        Sid    = "WriteApplicationLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "${aws_cloudwatch_log_group.api.arn}:*",
          "${aws_cloudwatch_log_group.mock_uber.arn}:*",
        ]
      },
      {
        Sid      = "InjectApplicationSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = data.aws_secretsmanager_secret.application.arn
      },
    ]
  })
  task_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "ApplicationTables"
      Effect = "Allow"
      Action = [
        "dynamodb:DeleteItem",
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
      ]
      Resource = concat(
        values(local.table_arns),
        ["${local.table_arns.trips}/index/by_session"],
      )
    }]
  })
}

resource "aws_iam_role" "execution" {
  name                 = local.execution_role_name
  assume_role_policy   = local.task_trust_policy
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/route-buddy-aws-demo-execution-boundary"
}

resource "aws_iam_role_policy" "execution" {
  name   = local.execution_role_name
  role   = aws_iam_role.execution.id
  policy = local.execution_policy
}

resource "aws_iam_role" "task" {
  name                 = local.task_role_name
  assume_role_policy   = local.task_trust_policy
  permissions_boundary = "arn:aws:iam::${var.aws_account_id}:policy/route-buddy-aws-demo-task-boundary"
}

resource "aws_iam_role_policy" "task" {
  name   = local.task_role_name
  role   = aws_iam_role.task.id
  policy = local.task_policy
}
