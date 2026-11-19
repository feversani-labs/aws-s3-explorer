output "lambda_function_url" {
  description = "URL HTTPS de la Lambda (requiere autenticación IAM)"
  value       = aws_lambda_function_url.explorer_api.function_url
}

output "broker_role_arn" {
  description = "ARN del BrokerRole para generación de sesiones STS"
  value       = aws_iam_role.broker_role.arn
}

output "dynamodb_table_name" {
  description = "Nombre de la tabla DynamoDB para auditoría y sesiones"
  value       = aws_dynamodb_table.idp_table.name
}

