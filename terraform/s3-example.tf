locals {
  bucket_names = toset(["example-1", "example-2"])
}

resource "aws_s3_bucket" "example" {
  for_each = local.bucket_names
  bucket = "${var.owner}-${each.key}-${time_static.this.unix}"

  tags = {
    Name        = "${var.owner}-${each.key}-${time_static.this.unix}"
    Environment = var.environment
    Owner       = var.owner
  }
  
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.example

  bucket = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.example

  bucket = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.example

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_ssm_parameter" "bucket_name" {
  for_each = aws_s3_bucket.example

  name        = "/ephemeral-aws-sandbox/buckets/bucket-name-${each.key}"
  description = ""
  type        = "String"
  value       = each.value.bucket

  tags = {
    Environment = var.environment
    Owner       = var.owner
  }
}
