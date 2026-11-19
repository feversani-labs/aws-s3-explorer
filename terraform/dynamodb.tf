resource "aws_dynamodb_table" "idp_table" {
  name         = "${var.owner}-${var.environment}-s3-explorer-idp"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

#   ttl {
#     attribute_name = "expires_at"
#     enabled        = true
#   }

  tags = {
    Name        = "${var.owner}-${var.environment}-s3-explorer-idp"
    Environment = var.environment
    Owner       = var.owner
  }
}
