terraform {
  backend "s3" {
    bucket       = ""
    key          = "bootstrap/terraform.tfstate"
    region       = ""
    encrypt      = true
    use_lockfile = true
  }
}
