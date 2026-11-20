output "application_url" {
  description = "URL publica del Application Load Balancer para acceder a S3 Explorer"
  value       = "http://${aws_lb.app.dns_name}"
}

output "alb_dns_name" {
  description = "Nombre DNS del ALB"
  value       = aws_lb.app.dns_name
}

output "ec2_private_ip" {
  description = "IP privada de la instancia EC2 en la subred privada"
  value       = aws_instance.app.private_ip
}

output "broker_role_arn" {
  description = "ARN del BrokerRole para generación de sesiones STS"
  value       = aws_iam_role.broker_role.arn
}

output "dynamodb_table_name" {
  description = "Nombre de la tabla DynamoDB para auditoría y sesiones"
  value       = aws_dynamodb_table.idp_table.name
}
