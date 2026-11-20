resource "aws_security_group" "alb" {
  name        = "${var.owner}-${var.environment}-alb-sg"
  description = "Permite trafico HTTP publico hacia el Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP desde cualquier origen"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-alb-sg"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_security_group" "ec2" {
  name        = "${var.owner}-${var.environment}-ec2-sg"
  description = "Permite trafico hacia la EC2 privada unicamente desde el ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP exclusivamente desde el Security Group del ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Salida a traves del NAT Gateway para Docker Hub y APIs de AWS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-ec2-sg"
    Environment = var.environment
    Owner       = var.owner
  }
}
