resource "aws_iam_openid_connect_provider" "github" {
  count = local.adopt_github_oidc_provider ? 0 : 1

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = []
}

data "aws_iam_openid_connect_provider" "github" {
  count = local.adopt_github_oidc_provider ? 1 : 0

  arn = var.github_oidc_provider_arn

  lifecycle {
    postcondition {
      condition     = self.url == "https://token.actions.githubusercontent.com"
      error_message = "The adopted OIDC provider must use GitHub's exact issuer."
    }

    postcondition {
      condition     = contains(self.client_id_list, "sts.amazonaws.com")
      error_message = "The adopted OIDC provider must trust the AWS STS audience."
    }
  }
}

locals {
  bootstrap_trust_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = local.github_oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.github_oidc_provider_path}:aud" = "sts.amazonaws.com"
          "${local.github_oidc_provider_path}:sub" = "repo:${local.repository}:environment:aws-bootstrap"
        }
      }
    }]
  })

  demo_trust_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = local.github_oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.github_oidc_provider_path}:aud" = "sts.amazonaws.com"
          "${local.github_oidc_provider_path}:sub" = "repo:${local.repository}:environment:aws-demo"
        }
      }
    }]
  })

  task_boundary_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "DynamoDBApplicationTables"
      Effect = "Allow"
      Action = [
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:ConditionCheckItem",
        "dynamodb:DeleteItem",
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:UpdateItem",
      ]
      Resource = [
        "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${local.project}-aws-demo-*",
        "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${local.project}-aws-demo-*/index/*",
      ]
    }]
  })

  execution_boundary_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ECRImagePull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
        ]
        Resource = local.ecr_repository_arns
      },
      {
        Sid      = "ECRAuthorization"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "ApplicationLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:DescribeLogStreams",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/route-buddy/aws-demo/*:*"
      },
      {
        Sid      = "ApplicationSecretInjection"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:route-buddy/aws-demo/application-*"
      },
    ]
  })

  demo_deploy_policy_statements = concat([
    {
      Sid      = "ListDemoState"
      Effect   = "Allow"
      Action   = "s3:ListBucket"
      Resource = local.state_bucket_arn
      Condition = {
        StringEquals = {
          "s3:prefix" = [local.demo_state_key, "${local.demo_state_key}.tflock"]
        }
      }
    },
    {
      Sid      = "ReadWriteDemoState"
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject"]
      Resource = "${local.state_bucket_arn}/${local.demo_state_key}"
    },
    {
      Sid      = "LockDemoState"
      Effect   = "Allow"
      Action   = ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"]
      Resource = "${local.state_bucket_arn}/${local.demo_state_key}.tflock"
    },
    {
      Sid    = "DenyOtherState"
      Effect = "Deny"
      Action = "s3:*"
      Resource = [
        "${local.state_bucket_arn}/bootstrap/*",
        "${local.state_bucket_arn}/environments/production/*",
      ]
    },
    {
      Sid      = "AuthorizeECR"
      Effect   = "Allow"
      Action   = "ecr:GetAuthorizationToken"
      Resource = "*"
    },
    {
      Sid    = "PushRouteBuddyImages"
      Effect = "Allow"
      Action = [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:CompleteLayerUpload",
        "ecr:DescribeImages",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart",
      ]
      Resource = local.ecr_repository_arns
    },
    {
      Sid      = "CreateBoundedExecutionRole"
      Effect   = "Allow"
      Action   = "iam:CreateRole"
      Resource = local.application_role_arns[0]
      Condition = {
        StringEquals = {
          "iam:PermissionsBoundary" = aws_iam_policy.runtime_boundary["execution"].arn
        }
      }
    },
    {
      Sid      = "CreateBoundedTaskRole"
      Effect   = "Allow"
      Action   = "iam:CreateRole"
      Resource = local.application_role_arns[1]
      Condition = {
        StringEquals = {
          "iam:PermissionsBoundary" = aws_iam_policy.runtime_boundary["task"].arn
        }
      }
    },
    {
      Sid    = "ManageBoundedApplicationRoles"
      Effect = "Allow"
      Action = [
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:PutRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
      ]
      Resource = local.application_role_arn_glob
    },
    {
      Sid      = "PassExactApplicationRoles"
      Effect   = "Allow"
      Action   = ["iam:GetRole", "iam:PassRole"]
      Resource = local.application_role_arns
      Condition = {
        StringEquals = {
          "iam:PassedToService" = "ecs-tasks.amazonaws.com"
        }
      }
    },
    {
      Sid    = "DenyBoundaryRemoval"
      Effect = "Deny"
      Action = ["iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary"]
      Resource = [
        local.application_role_arn_glob,
        local.demo_deploy_role_arn,
      ]
    },
    {
      Sid    = "DenySelfAndBootstrapMutation"
      Effect = "Deny"
      Action = "iam:*"
      Resource = [
        local.runtime_boundary_arns["execution"],
        local.runtime_boundary_arns["task"],
        local.bootstrap_role_arn,
        local.demo_deploy_role_arn,
        local.github_oidc_provider_arn,
      ]
    },
    {
      Sid    = "ReadApplicationInfrastructure"
      Effect = "Allow"
      Action = [
        "acm:DescribeCertificate",
        "acm:ListTagsForCertificate",
        "dynamodb:DescribeContinuousBackups",
        "dynamodb:DescribeTable",
        "dynamodb:ListTagsOfResource",
        "ec2:Describe*",
        "ecs:Describe*",
        "ecs:List*",
        "elasticloadbalancing:Describe*",
        "logs:Describe*",
        "route53:Get*",
        "route53:List*",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetResourcePolicy",
        "secretsmanager:ListSecretVersionIds",
      ]
      Resource = "*"
    },
    {
      Sid    = "ManageNamedApplicationResources"
      Effect = "Allow"
      Action = [
        "dynamodb:CreateTable",
        "dynamodb:DeleteTable",
        "dynamodb:TagResource",
        "dynamodb:UntagResource",
        "dynamodb:UpdateContinuousBackups",
        "dynamodb:UpdateTable",
        "ecs:*",
        "elasticloadbalancing:*",
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:PutRetentionPolicy",
        "logs:TagResource",
        "logs:UntagResource",
        "secretsmanager:CreateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:PutResourcePolicy",
        "secretsmanager:TagResource",
        "secretsmanager:UntagResource",
        "secretsmanager:UpdateSecret",
      ]
      Resource = [
        "arn:aws:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${local.project}-aws-demo-*",
        "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:cluster/${local.project}-aws-demo-*",
        "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:service/${local.project}-aws-demo-*/*",
        "arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:task-definition/${local.project}-aws-demo-*:*",
        "arn:aws:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:listener/app/${local.project}-aws-demo-*/*/*",
        "arn:aws:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:loadbalancer/app/${local.project}-aws-demo-*/*",
        "arn:aws:elasticloadbalancing:${var.aws_region}:${var.aws_account_id}:targetgroup/${local.project}-aws-demo-*/*",
        "arn:aws:logs:${var.aws_region}:${var.aws_account_id}:log-group:/route-buddy/aws-demo/*",
        "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:route-buddy/aws-demo/*",
      ]
    },
    {
      Sid    = "CreateTaggedApplicationResources"
      Effect = "Allow"
      Action = [
        "acm:RequestCertificate",
        "ec2:AllocateAddress",
        "ec2:CreateInternetGateway",
        "ec2:CreateNatGateway",
        "ec2:CreateRouteTable",
        "ec2:CreateSecurityGroup",
        "ec2:CreateSubnet",
        "ec2:CreateVpc",
      ]
      Resource = "*"
      Condition = {
        StringEquals = {
          "aws:RequestTag/Environment" = "aws-demo"
          "aws:RequestTag/Project"     = local.project
        }
      }
    },
    {
      Sid    = "ManageTaggedApplicationResources"
      Effect = "Allow"
      Action = [
        "acm:AddTagsToCertificate",
        "acm:DeleteCertificate",
        "acm:RemoveTagsFromCertificate",
        "ec2:AssociateRouteTable",
        "ec2:AttachInternetGateway",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:CreateRoute",
        "ec2:CreateTags",
        "ec2:DeleteInternetGateway",
        "ec2:DeleteNatGateway",
        "ec2:DeleteRoute",
        "ec2:DeleteRouteTable",
        "ec2:DeleteSecurityGroup",
        "ec2:DeleteSubnet",
        "ec2:DeleteTags",
        "ec2:DeleteVpc",
        "ec2:DetachInternetGateway",
        "ec2:DisassociateRouteTable",
        "ec2:ModifySecurityGroupRules",
        "ec2:ModifySubnetAttribute",
        "ec2:ModifyVpcAttribute",
        "ec2:ReleaseAddress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress",
      ]
      Resource = "*"
      Condition = {
        StringEquals = {
          "aws:ResourceTag/Environment" = "aws-demo"
          "aws:ResourceTag/Project"     = local.project
        }
      }
    },
    ], local.manage_route53_zone ? [
    {
      Sid      = "ManageExactHostedZone"
      Effect   = "Allow"
      Action   = "route53:ChangeResourceRecordSets"
      Resource = "arn:aws:route53:::hostedzone/${var.route53_hosted_zone_id}"
    },
  ] : [])

  demo_deploy_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.demo_deploy_policy_statements
  })

  bootstrap_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ManageBootstrapIAM"
        Effect = "Allow"
        Action = [
          "iam:CreatePolicy",
          "iam:CreatePolicyVersion",
          "iam:CreateRole",
          "iam:DeleteOpenIDConnectProvider",
          "iam:DeletePolicy",
          "iam:DeletePolicyVersion",
          "iam:DeleteRole",
          "iam:DeleteRolePolicy",
          "iam:GetOpenIDConnectProvider",
          "iam:GetPolicy",
          "iam:GetPolicyVersion",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListPolicyVersions",
          "iam:ListRolePolicies",
          "iam:PutRolePolicy",
          "iam:TagOpenIDConnectProvider",
          "iam:TagPolicy",
          "iam:TagRole",
          "iam:UntagOpenIDConnectProvider",
          "iam:UntagPolicy",
          "iam:UntagRole",
          "iam:UpdateAssumeRolePolicy",
          "iam:UpdateOpenIDConnectProviderThumbprint",
        ]
        Resource = [
          local.runtime_boundary_arns["execution"],
          local.runtime_boundary_arns["task"],
          local.bootstrap_role_arn,
          local.demo_deploy_role_arn,
          local.github_oidc_provider_arn,
        ]
      },
      {
        Sid      = "CreateGitHubOIDCProvider"
        Effect   = "Allow"
        Action   = "iam:CreateOpenIDConnectProvider"
        Resource = "*"
      },
      {
        Sid      = "CreateStateBucket"
        Effect   = "Allow"
        Action   = "s3:CreateBucket"
        Resource = "*"
      },
      {
        Sid      = "ManageStateBucket"
        Effect   = "Allow"
        Action   = "s3:*"
        Resource = [local.state_bucket_arn, "${local.state_bucket_arn}/*"]
      },
      {
        Sid      = "CreateTaggedRepositories"
        Effect   = "Allow"
        Action   = "ecr:CreateRepository"
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Project" = local.project
          }
        }
      },
      {
        Sid      = "ManageRouteBuddyRepositories"
        Effect   = "Allow"
        Action   = "ecr:*"
        Resource = local.ecr_repository_arns
      },
    ]
  })
}

resource "aws_iam_policy" "runtime_boundary" {
  for_each = local.runtime_boundary_names

  name        = each.value
  description = "Maximum permissions for the Route Buddy aws-demo ${each.key} role."
  policy      = each.key == "execution" ? local.execution_boundary_policy : local.task_boundary_policy
}

resource "aws_iam_role" "demo_deploy" {
  name               = local.demo_deploy_role_name
  assume_role_policy = local.demo_trust_policy
}

resource "aws_iam_role_policy" "demo_deploy" {
  name   = "route-buddy-aws-demo-deploy"
  role   = aws_iam_role.demo_deploy.id
  policy = local.demo_deploy_policy
}

resource "aws_iam_role" "bootstrap" {
  name               = local.bootstrap_role_name
  assume_role_policy = local.bootstrap_trust_policy
}

resource "aws_iam_role_policy" "bootstrap" {
  name   = "route-buddy-bootstrap"
  role   = aws_iam_role.bootstrap.id
  policy = local.bootstrap_policy
}
