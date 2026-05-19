data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

# Subnets
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name                                            = "${var.project_name}-pub-${count.index == 0 ? "a" : "b"}"
    "kubernetes.io/role/elb"                        = "1"
    "kubernetes.io/cluster/${var.eks_cluster_name}" = "owned"
  }
}

resource "aws_subnet" "app_private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 6, count.index + 1) # Using same pattern as reference
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name                                            = "${var.project_name}-app-${count.index == 0 ? "a" : "b"}"
    "kubernetes.io/role/internal-elb"               = "1"
    "kubernetes.io/cluster/${var.eks_cluster_name}" = "owned"
    "karpenter.sh/discovery"                        = var.eks_cluster_name
  }
}

resource "aws_subnet" "db_private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 12) # Using same pattern as reference
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.project_name}-db-${count.index == 0 ? "a" : "b"}"
  }
}

# NAT Gateways — single-NAT cost-saving 패턴 (dev/demo).
# 비용절감플랜/up.sh 가 1개 NAT 만 만들고 두 AZ 가 공유. multi-AZ 복원력은
# 포기하지만 비용 ~50% 절감 + production 전환 시 count=2 로 되돌리면 됨.
resource "aws_eip" "nat" {
  count = 1
  tags = {
    Name = "${var.project_name}-eip-a"
  }
}

resource "aws_nat_gateway" "nat" {
  count         = 1
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.project_name}-nat-gw-a"
  }
}

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "${var.project_name}-rtb-public"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "app" {
  count  = 2
  vpc_id = aws_vpc.main.id

  # single-NAT 패턴: 두 AZ 모두 nat[0] 공유 (count=1 NAT 와 일관).
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[0].id
  }

  tags = {
    Name = "${var.project_name}-rtb-app-${count.index == 0 ? "a" : "b"}"
  }
}

resource "aws_route_table_association" "app" {
  count          = 2
  subnet_id      = aws_subnet.app_private[count.index].id
  route_table_id = aws_route_table.app[count.index].id
}

resource "aws_route_table" "db" {
  count  = 2
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-rtb-db-${count.index == 0 ? "a" : "b"}"
  }
}

resource "aws_route_table_association" "db" {
  count          = 2
  subnet_id      = aws_subnet.db_private[count.index].id
  route_table_id = aws_route_table.db[count.index].id
}

# Security Groups
resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.project_name}-vpc-endpoints-sg"
  description = "Security group for VPC Endpoints"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-vpc-endpoints-sg"
  }
}

# VPC Endpoints
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat([aws_route_table.public.id], aws_route_table.app[*].id)

  tags = {
    Name = "${var.project_name}-s3-endpoint"
  }
}

# Kinesis VPC endpoint — single-NAT cost-saving 패턴에서 제거.
# KDS 트래픽이 NAT GW egress 로 흘러도 dev/demo 규모에선 비용 차이 미미.
# Production 전환 시 endpoint 다시 추가 (Interface endpoint 약 $7~15/월).
