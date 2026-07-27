terraform {
  backend "s3" {
    bucket       = ""
    key          = "environments/aws-demo/terraform.tfstate"
    region       = ""
    encrypt      = true
    use_lockfile = true
  }
}
