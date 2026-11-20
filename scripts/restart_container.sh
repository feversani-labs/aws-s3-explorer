#!/usr/bin/env bash
# ==============================================================================
# Reiniciar el contenedor en EC2 inyectando las variables de entorno via SSM
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${REPO_DIR}/.aws-credentials" ]; then
  export AWS_PROFILE="${AWS_PROFILE:-ephemeral}"
  export AWS_SHARED_CREDENTIALS_FILE="${AWS_SHARED_CREDENTIALS_FILE:-${REPO_DIR}/.aws-credentials}"
  export AWS_REGION="${AWS_REGION:-us-east-1}"
fi

echo "🔍 Buscando la instancia EC2 activa de S3 Explorer..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=*s3-explorer*" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" == "None" ]; then
  echo "❌ No se encontró instancia EC2 en estado 'running'. Verificá tu infraestructura."
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BROKER_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/fvrsn-sandbox-s3-broker"
DYNAMODB_TABLE="fvrsn-sandbox-s3-explorer-idp"

echo "✅ Instancia encontrada: ${INSTANCE_ID}"
echo "👤 Cuenta AWS          : ${ACCOUNT_ID}"
echo "🛡️  Broker Role         : ${BROKER_ROLE_ARN}"
echo "🗄️  DynamoDB Table      : ${DYNAMODB_TABLE}"
echo ""
echo "🚀 Enviando comando SSM para reiniciar el contenedor Docker con las variables..."

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "Restart s3-explorer with broker environment variables" \
  --parameters 'commands=[
    "docker pull feversani/aws-s3-explorer:latest || true",
    "docker stop s3-explorer 2>/dev/null || true",
    "docker rm s3-explorer 2>/dev/null || true",
    "docker run -d --restart always --name s3-explorer -p 80:8080 -e MODE=sandbox -e BROKER_ROLE_ARN=\"'"$BROKER_ROLE_ARN"'\" -e DYNAMODB_TABLE=\"'"$DYNAMODB_TABLE"'\" -e AWS_REGION=us-east-1 feversani/aws-s3-explorer:latest"
  ]' \
  --query "Command.CommandId" \
  --output text)

echo "⏳ Esperando confirmación de AWS SSM (Command ID: ${COMMAND_ID})..."
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"

STATUS=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query "Status" \
  --output text)

if [ "$STATUS" == "Success" ]; then
  echo "🎉 ¡Contenedor reiniciado y configurado exitosamente en EC2!"
  echo "👉 Ahora podés ejecutar de nuevo: make test-post"
else
  echo "⚠️ Estado del comando SSM: ${STATUS}"
  aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --query "StandardOutputContent" --output text
fi
