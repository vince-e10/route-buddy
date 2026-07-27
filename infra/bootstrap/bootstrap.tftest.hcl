mock_provider "aws" {}

run "security_contract" {
  command = apply

  variables {
    aws_account_id         = "123456789012"
    aws_region             = "ap-southeast-1"
    route53_hosted_zone_id = "Z0123456789ABC"
  }

  assert {
    condition     = aws_s3_bucket.state.bucket == "route-buddy-tfstate-123456789012-ap-southeast-1"
    error_message = "The state bucket name must be account and region scoped."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls &&
      aws_s3_bucket_public_access_block.state.block_public_policy &&
      aws_s3_bucket_public_access_block.state.ignore_public_acls &&
      aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "The state bucket must block every form of public access."
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "The state bucket must retain recoverable object versions."
  }

  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The state bucket must encrypt objects by default."
  }

  assert {
    condition     = strcontains(aws_s3_bucket_policy.state.policy, "aws:SecureTransport")
    error_message = "The state bucket policy must reject non-TLS requests."
  }

  assert {
    condition = (
      aws_iam_openid_connect_provider.github[0].url == "https://token.actions.githubusercontent.com" &&
      length(aws_iam_openid_connect_provider.github[0].client_id_list) == 1 &&
      contains(aws_iam_openid_connect_provider.github[0].client_id_list, "sts.amazonaws.com")
    )
    error_message = "The GitHub OIDC provider must use the exact issuer and STS audience."
  }

  assert {
    condition = (
      strcontains(local.bootstrap_trust_policy, "repo:vince-e10/route-buddy:environment:aws-bootstrap") &&
      strcontains(local.bootstrap_trust_policy, "sts.amazonaws.com")
    )
    error_message = "Bootstrap trust must require the exact GitHub Environment subject and audience."
  }

  assert {
    condition = (
      strcontains(local.demo_trust_policy, "repo:vince-e10/route-buddy:environment:aws-demo") &&
      strcontains(local.demo_trust_policy, "sts.amazonaws.com")
    )
    error_message = "Demo trust must require the exact GitHub Environment subject and audience."
  }

  assert {
    condition = alltrue([
      for repository in values(aws_ecr_repository.images) :
      repository.image_tag_mutability == "IMMUTABLE" &&
      repository.image_scanning_configuration[0].scan_on_push &&
      repository.encryption_configuration[0].encryption_type == "AES256"
    ])
    error_message = "Every ECR repository must be immutable, scanned on push, and encrypted."
  }

  assert {
    condition = (
      strcontains(local.demo_deploy_policy, "environments/aws-demo/terraform.tfstate") &&
      strcontains(local.demo_deploy_policy, "environments/aws-demo/terraform.tfstate.tflock") &&
      strcontains(local.demo_deploy_policy, "DenyOtherState") &&
      strcontains(local.demo_deploy_policy, "bootstrap/*") &&
      strcontains(local.demo_deploy_policy, "environments/production/*")
    )
    error_message = "The demo role must be isolated to its own state and lock objects."
  }

  assert {
    condition = (
      strcontains(local.demo_deploy_policy, "route-buddy-aws-demo-execution") &&
      strcontains(local.demo_deploy_policy, "route-buddy-aws-demo-task") &&
      strcontains(local.demo_deploy_policy, "iam:PassedToService")
    )
    error_message = "PassRole must be limited to the two ECS roles and ECS tasks."
  }

  assert {
    condition = alltrue([
      for required in [
        "dynamodb:DescribeTimeToLive",
        "dynamodb:UpdateTimeToLive",
        "iam:CreateServiceLinkedRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "logs:ListTagsForResource",
        "cluster/route-buddy-aws-demo",
        "service/route-buddy-aws-demo/route-buddy-aws-demo",
        "task-definition/route-buddy-aws-demo:*",
        "loadbalancer/app/route-buddy-aws-demo/*",
        "listener/app/route-buddy-aws-demo/*/*",
      ] : strcontains(local.demo_deploy_policy, required)
    ])
    error_message = "The demo role must cover the provider APIs and exact-name runtime ARNs."
  }

  assert {
    condition = (
      strcontains(local.demo_deploy_policy, "DenySelfAndBootstrapMutation") &&
      strcontains(local.demo_deploy_policy, "DenyBoundaryRemoval")
    )
    error_message = "The demo role must deny self-management and permissions-boundary removal."
  }

  assert {
    condition     = strcontains(local.demo_deploy_policy, "arn:aws:route53:::hostedzone/Z0123456789ABC")
    error_message = "Route53 writes must be limited to the configured hosted zone."
  }

  assert {
    condition = (
      strcontains(local.demo_deploy_policy, local.runtime_boundary_arns["execution"]) &&
      strcontains(local.demo_deploy_policy, local.runtime_boundary_arns["task"]) &&
      !strcontains(local.task_boundary_policy, "secretsmanager:GetSecretValue")
    )
    error_message = "Execution and task roles must have distinct enforced permission ceilings."
  }

  assert {
    condition = (
      length(local.demo_deploy_policy) <= 10240 &&
      length(local.bootstrap_policy) <= 10240 &&
      length(local.execution_boundary_policy) <= 6144 &&
      length(local.task_boundary_policy) <= 6144
    )
    error_message = "IAM policies must fit AWS role-inline and managed-policy size limits."
  }
}

run "adopt_existing_oidc_provider" {
  command = apply

  variables {
    aws_account_id           = "123456789012"
    aws_region               = "ap-southeast-1"
    github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  }

  override_data {
    target = data.aws_iam_openid_connect_provider.github[0]
    values = {
      arn            = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
      url            = "https://token.actions.githubusercontent.com"
      client_id_list = ["sts.amazonaws.com"]
    }
  }

  assert {
    condition = (
      length(aws_iam_openid_connect_provider.github) == 0 &&
      local.github_oidc_provider_arn == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    )
    error_message = "Adoption must verify and reuse the exact account-level GitHub provider."
  }
}
