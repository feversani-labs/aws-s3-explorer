resource "aws_iam_role" "ec2_role" {
  name = "${var.owner}-${var.environment}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "${var.owner}-${var.environment}-ec2-role"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ec2_dynamodb" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
}

resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.owner}-${var.environment}-ec2-instance-profile"
  role = aws_iam_role.ec2_role.name

  tags = {
    Name        = "${var.owner}-${var.environment}-ec2-instance-profile"
    Environment = var.environment
    Owner       = var.owner
  }
}
