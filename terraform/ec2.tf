resource "aws_instance" "app" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = "t3.micro"
  subnet_id                   = aws_subnet.private_0.id
  associate_public_ip_address = false
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  iam_instance_profile        = aws_iam_instance_profile.ec2_profile.name

  # Hop limit 2 para que Docker pueda consultar IMDSv2
  metadata_options {
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 2
  }

  user_data = <<-EOF
    #!/bin/bash
    dnf update -y
    dnf install -y docker
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # Variables de entorno pasadas dinámicamente desde Terraform
    export DYNAMODB_TABLE="${aws_dynamodb_table.idp_table.name}"
    export BROKER_ROLE_ARN="${aws_iam_role.broker_role.arn}"
    export AWS_REGION="${var.region}"
    export DEFAULT_ACCOUNT_ID="${data.aws_caller_identity.current.account_id}"

    # Descargar y correr la app desde Docker Hub en el puerto 80
    docker pull feversani/aws-s3-explorer:latest || true
    docker run -d --restart always --name s3-explorer \
      -p 80:8080 \
      -e MODE=sandbox \
      -e DYNAMODB_TABLE="$DYNAMODB_TABLE" \
      -e BROKER_ROLE_ARN="$BROKER_ROLE_ARN" \
      -e AWS_REGION="$AWS_REGION" \
      -e DEFAULT_ACCOUNT_ID="$DEFAULT_ACCOUNT_ID" \
      feversani/aws-s3-explorer:latest || true
  EOF

  user_data_replace_on_change = true

  tags = {
    Name        = "${var.owner}-${var.environment}-s3-explorer-ec2"
    Environment = var.environment
    Owner       = var.owner
  }
}
