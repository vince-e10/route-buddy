resource "aws_vpc" "demo" {
  cidr_block                       = var.vpc_cidr
  enable_dns_support               = true
  enable_dns_hostnames             = true
  assign_generated_ipv6_cidr_block = length(var.ingress_ipv6_cidrs) > 0

  tags = {
    Name = local.name_prefix
  }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = {
    Name = local.name_prefix
  }
}

resource "aws_subnet" "public" {
  for_each = { for index, cidr in var.public_subnet_cidrs : tostring(index) => cidr }

  vpc_id            = aws_vpc.demo.id
  availability_zone = var.availability_zones[tonumber(each.key)]
  cidr_block        = each.value
  ipv6_cidr_block = (
    length(var.ingress_ipv6_cidrs) > 0
    ? cidrsubnet(aws_vpc.demo.ipv6_cidr_block, 8, tonumber(each.key))
    : null
  )

  tags = {
    Name = "${local.name_prefix}-public-${tonumber(each.key) + 1}"
  }
}

resource "aws_subnet" "private" {
  for_each = { for index, cidr in var.private_subnet_cidrs : tostring(index) => cidr }

  vpc_id            = aws_vpc.demo.id
  availability_zone = var.availability_zones[tonumber(each.key)]
  cidr_block        = each.value

  tags = {
    Name = "${local.name_prefix}-private-${tonumber(each.key) + 1}"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  depends_on = [aws_internet_gateway.demo]

  tags = {
    Name = "${local.name_prefix}-nat"
  }
}

resource "aws_nat_gateway" "demo" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public["0"].id

  depends_on = [aws_internet_gateway.demo]

  tags = {
    Name = local.name_prefix
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.demo.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }

  dynamic "route" {
    for_each = length(var.ingress_ipv6_cidrs) > 0 ? [true] : []

    content {
      ipv6_cidr_block = "::/0"
      gateway_id      = aws_internet_gateway.demo.id
    }
  }

  tags = {
    Name = "${local.name_prefix}-public"
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  for_each = aws_subnet.private

  vpc_id = aws_vpc.demo.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.demo.id
  }

  tags = {
    Name = "${local.name_prefix}-private-${tonumber(each.key) + 1}"
  }
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.demo.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for route_table in aws_route_table.private : route_table.id]

  tags = {
    Name = "${local.name_prefix}-dynamodb"
  }
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "CIDR-restricted HTTP and HTTPS ingress to the demo ALB."
  vpc_id      = aws_vpc.demo.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_ipv4" {
  for_each = toset(var.ingress_ipv4_cidrs)

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https_ipv4" {
  for_each = toset(var.ingress_ipv4_cidrs)

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http_ipv6" {
  for_each = toset(var.ingress_ipv6_cidrs)

  security_group_id = aws_security_group.alb.id
  cidr_ipv6         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https_ipv6" {
  for_each = toset(var.ingress_ipv6_cidrs)

  security_group_id = aws_security_group.alb.id
  cidr_ipv6         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_ipv4" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "task" {
  name        = "${local.name_prefix}-task"
  description = "API ingress from the ALB only."
  vpc_id      = aws_vpc.demo.id
}

resource "aws_vpc_security_group_ingress_rule" "task_api" {
  security_group_id            = aws_security_group.task.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "task_ipv4" {
  security_group_id = aws_security_group.task.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
