output "state_bucket_name" {
  value = aws_s3_bucket.state.bucket
}

output "aws_region" {
  value = var.aws_region
}

output "bootstrap_role_arn" {
  value = aws_iam_role.bootstrap.arn
}

output "demo_deployment_role_arn" {
  value = aws_iam_role.demo_deploy.arn
}

output "api_repository_url" {
  value = aws_ecr_repository.images["route-buddy/api"].repository_url
}

output "mock_uber_repository_url" {
  value = aws_ecr_repository.images["route-buddy/mock-uber"].repository_url
}
