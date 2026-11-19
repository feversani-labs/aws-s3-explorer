locals {
  bucket_name = "${var.owner}-bucket-code-${time_static.this.unix}"
}

resource "aws_s3_bucket" "code" {
  bucket = local.bucket_name

  tags = {
    Name        = local.bucket_name
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_s3_bucket_public_access_block" "code" {
  bucket = aws_s3_bucket.code.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "code" {
  bucket = aws_s3_bucket.code.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "code" {
  bucket = aws_s3_bucket.code.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_ssm_parameter" "code_bucket" {
  name        = "/ephemeral-aws-sandbox/code/bucket_name"
  description = ""
  type        = "String"
  value       = aws_s3_bucket.code.bucket

  tags = {
    Environment = var.environment
    Owner       = var.owner
  }
}