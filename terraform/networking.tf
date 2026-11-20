resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name        = "${var.owner}-${var.environment}-vpc"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_subnet" "public_0" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.owner}-${var.environment}-public-subnet-0"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true

  tags = {
    Name        = "${var.owner}-${var.environment}-public-subnet-1"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_subnet" "private_0" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.3.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name        = "${var.owner}-${var.environment}-private-subnet-0"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name        = "${var.owner}-${var.environment}-igw"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_eip" "nat_eip" {
  domain     = "vpc"
  depends_on = [aws_internet_gateway.igw]

  tags = {
    Name        = "${var.owner}-${var.environment}-nat-eip"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat_eip.id
  subnet_id     = aws_subnet.public_0.id
  depends_on    = [aws_internet_gateway.igw]

  tags = {
    Name        = "${var.owner}-${var.environment}-nat"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-public-rt"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_route_table_association" "public_0" {
  subnet_id      = aws_subnet.public_0.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "public_1" {
  subnet_id      = aws_subnet.public_1.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat.id
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-private-rt"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_route_table_association" "private_0" {
  subnet_id      = aws_subnet.private_0.id
  route_table_id = aws_route_table.private.id
}
