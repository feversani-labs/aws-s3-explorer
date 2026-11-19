resource "aws_iam_role" "lambda_exec" {
  name = "lambda_execution_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "lambda_execution_role"
    Environment = var.environment
    Owner       = var.owner
  }
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
}


resource "aws_lambda_function" "explorer_api" {
  function_name    = "${var.owner}-${var.environment}-s3-explorer-idp"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.lambda_dummy.output_path
  source_code_hash = data.archive_file.lambda_dummy.output_base64sha256
  timeout          = 10
  memory_size      = 256

  environment {
    variables = {
      MODE            = "sandbox"
      DYNAMODB_TABLE  = aws_dynamodb_table.idp_table.name
      BROKER_ROLE_ARN = aws_iam_role.broker_role.arn
    }
  }

  tags = {
    Name        = "${var.owner}-${var.environment}-s3-explorer-idp"
    Environment = var.environment
    Owner       = var.owner
  }

  # Evita que futuros 'terraform apply' pisen el código real subido por CI/CD
  lifecycle {
    ignore_changes = [
      filename,
      source_code_hash
    ]
  }
}

resource "aws_lambda_function_url" "explorer_api" {
  function_name      = aws_lambda_function.explorer_api.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_ssm_parameter" "lambda_name" {
  name  = "/ephemeral-aws-sandbox/s3-explorer/lambda-name"
  type  = "String"
  value = aws_lambda_function.explorer_api.function_name

  tags = {
    Environment = var.environment
    Owner       = var.owner
  }
}
