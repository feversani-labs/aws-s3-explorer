#!/usr/bin/env bash
# ==============================================================================
# Diagnóstico de EC2: Ver estado de Docker y logs del contenedor s3-explorer
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${REPO_DIR}/.aws-credentials" ]; then
  export AWS_PROFILE="${AWS_PROFILE:-ephemeral}"
  export AWS_SHARED_CREDENTIALS_FILE="${AWS_SHARED_CREDENTIALS_FILE:-${REPO_DIR}/.aws-credentials}"
  export AWS_REGION="${AWS_REGION:-us-east-1}"
fi

echo "🔍 Buscando instancia EC2..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=*s3-explorer*" "Name=instance-state-name,Values=running" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" == "None" ]; then
  echo "❌ No se encontró instancia EC2 activa."
  exit 1
fi

echo "✅ Instancia: ${INSTANCE_ID}"
echo "📊 Consultando estado de Docker y logs del contenedor..."

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "echo \"=== DOCKER PS ===\"",
    "docker ps -a",
    "echo \"=== DOCKER LOGS ===\"",
    "docker logs --tail 30 s3-explorer 2>&1 || true",
    "echo \"=== PORT 80 LISTENER ===\"",
    "ss -tulpn | grep 80 || true"
  ]' \
  --query "Command.CommandId" \
  --output text)

aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"

echo ""
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query "StandardOutputContent" \
  --output text
