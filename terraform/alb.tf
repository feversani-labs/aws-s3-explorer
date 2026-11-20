resource "aws_lb" "app" {
  name               = "${var.owner}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets = [
    aws_subnet.public_0.id,
    aws_subnet.public_1.id
  ]

  enable_deletion_protection = false

  tags = {
    Name        = "${var.owner}-${var.environment}-alb"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_lb_target_group" "app" {
  name     = "${var.owner}-${var.environment}-tg"
  port     = 80
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/api/info"
    port                = "traffic-port"
    protocol            = "HTTP"
    interval            = 20
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-tg"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

resource "aws_lb_target_group_attachment" "app" {
  target_group_arn = aws_lb_target_group.app.arn
  target_id        = aws_instance.app.id
  port             = 80
}
