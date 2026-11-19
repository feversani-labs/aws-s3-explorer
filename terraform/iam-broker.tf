resource "aws_iam_role" "broker_role" {
  name = "${var.owner}-${var.environment}-s3-explorer-broker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = aws_iam_role.lambda_exec.arn }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "${var.owner}-${var.environment}-s3-explorer-broker-role"
    Environment = var.environment
    Owner       = var.owner
  }
}

# Techo máximo de permisos que el broker puede delegar sobre S3 (usando AWS Managed Policy compatible con KodeKloud)
resource "aws_iam_role_policy_attachment" "broker_s3_ceiling" {
  role       = aws_iam_role.broker_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}
