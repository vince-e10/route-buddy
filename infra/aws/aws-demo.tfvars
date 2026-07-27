aws_account_id         = "000000000000"
aws_region             = "ap-southeast-1"
availability_zones     = ["ap-southeast-1a", "ap-southeast-1b"]
vpc_cidr               = "10.24.0.0/16"
public_subnet_cidrs    = ["10.24.0.0/24", "10.24.1.0/24"]
private_subnet_cidrs   = ["10.24.10.0/24", "10.24.11.0/24"]
route53_hosted_zone_id = "Z0000000000000"
dns_name               = "route-buddy.example.com"
ingress_ipv4_cidrs     = ["203.0.113.0/24"]
ingress_ipv6_cidrs     = []

api_image       = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
mock_uber_image = "000000000000.dkr.ecr.ap-southeast-1.amazonaws.com/route-buddy/mock-uber@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
