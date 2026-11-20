#!/usr/bin/env bash
# ==============================================================================
# Script de prueba POST para aprovisionar sesiones efímeras JIT
# ==============================================================================
# Obtiene automáticamente el DNS del Application Load Balancer generado
# por Terraform (output 'application_url' o 'alb_dns_name') o AWS CLI.
#
# Variables opcionales:
#   ALB_URL          : URL base del Load Balancer (ej: http://mi-alb.elb.amazonaws.com)
#   BUCKET           : Nombre del bucket a acceder (auto-detectado si no se pasa)
#   USERNAME         : Usuario solicitante (default: dfeversani o $USER)
#   EMAIL            : Correo solicitante (default: dev@feversani.internal)
#   AWS_ACCOUNT_ID   : Cuenta AWS remota para Cross-Account (opcional)
#   DURATION_MINUTES : Duración de la sesión STS en minutos (default: 15)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 1. Asegurar credenciales y perfil AWS si existe .aws-credentials
if [ -f "${REPO_DIR}/.aws-credentials" ]; then
  export AWS_PROFILE="${AWS_PROFILE:-ephemeral}"
  export AWS_SHARED_CREDENTIALS_FILE="${AWS_SHARED_CREDENTIALS_FILE:-${REPO_DIR}/.aws-credentials}"
  export AWS_REGION="${AWS_REGION:-us-east-1}"
fi

# 2. Resolver URL del ALB (Prioridad: Variable de entorno -> Terraform output -> AWS CLI)
if [ -z "${ALB_URL}" ] && [ -n "${APP_URL}" ]; then
  ALB_URL="${APP_URL}"
fi

if [ -z "${ALB_URL}" ]; then
  echo "🔍 Detectando DNS del Load Balancer desde Terraform outputs..."
  
  # Intento 1: output 'application_url'
  TF_APP_URL=$(terraform -chdir="${REPO_DIR}/terraform" output -raw application_url 2>/dev/null || true)
  if [[ "${TF_APP_URL}" =~ ^http:// ]]; then
    ALB_URL="${TF_APP_URL}"
  fi

  # Intento 2: output 'alb_dns_name'
  if [ -z "${ALB_URL}" ]; then
    TF_DNS=$(terraform -chdir="${REPO_DIR}/terraform" output -raw alb_dns_name 2>/dev/null || true)
    if [ -n "${TF_DNS}" ] && [[ "${TF_DNS}" != *"No outputs found"* ]] && [[ "${TF_DNS}" != *"Warning"* ]] && [[ "${TF_DNS}" != *"Error"* ]]; then
      ALB_URL="http://${TF_DNS}"
    fi
  fi
fi

# Intento 3: Si Terraform no devolvió el output (ej: no está inicializado localmente), consultar a AWS CLI
if [ -z "${ALB_URL}" ] || [ "${ALB_URL}" = "http://" ]; then
  echo "🔍 Consultando Load Balancer a AWS CLI (fvrsn-sandbox-alb)..."
  AWS_ALB_DNS=$(aws elbv2 describe-load-balancers \
    --names "fvrsn-sandbox-alb" \
    --query 'LoadBalancers[0].DNSName' \
    --output text 2>/dev/null || true)

  if [ -n "${AWS_ALB_DNS}" ] && [ "${AWS_ALB_DNS}" != "None" ]; then
    ALB_URL="http://${AWS_ALB_DNS}"
  fi
fi

# Si después de todos los intentos no se obtuvo el Load Balancer, notificar error explícito
if [ -z "${ALB_URL}" ] || [ "${ALB_URL}" = "http://" ]; then
  echo ""
  echo "❌ Error: No se pudo obtener el DNS del Load Balancer automáticamente."
  echo "   Verificá que el stack de Terraform esté aplicado o pasá la URL manualmente:"
  echo ""
  echo "   👉 ALB_URL=\"http://<tu-alb-dns>\" make test-post"
  echo "   👉 o ejecutá: export ALB_URL=\"http://<tu-alb-dns>\""
  echo ""
  exit 1
fi

# Normalizar URL (quitar barra final si existe)
ALB_URL="${ALB_URL%/}"

# 3. Resolver Bucket de destino (Prioridad: Env var -> Terraform output -> SSM -> fallback)
TARGET_BUCKET="${BUCKET:-${BUCKET_NAME:-}}"
if [ -z "${TARGET_BUCKET}" ]; then
  # Intento 1: output 'example_bucket_1' de Terraform
  TF_BUCKET=$(terraform -chdir="${REPO_DIR}/terraform" output -raw example_bucket_1 2>/dev/null || true)
  if [ -n "${TF_BUCKET}" ] && [[ "${TF_BUCKET}" =~ ^fvrsn- ]]; then
    TARGET_BUCKET="${TF_BUCKET}"
  fi
fi

if [ -z "${TARGET_BUCKET}" ]; then
  # Intento 2: SSM Parameter Store
  SSM_BUCKET=$(aws ssm get-parameter \
    --name "/ephemeral-aws-sandbox/buckets/bucket-name-example-1" \
    --query 'Parameter.Value' \
    --output text 2>/dev/null || true)
  if [ -n "${SSM_BUCKET}" ] && [ "${SSM_BUCKET}" != "None" ]; then
    TARGET_BUCKET="${SSM_BUCKET}"
  fi
fi

if [ -z "${TARGET_BUCKET}" ]; then
  TARGET_BUCKET="fvrsn-example-1-secops"
fi

# 4. Parámetros de usuario y sesión
USER_NAME="${USERNAME:-dfeversani}"
USER_EMAIL="${EMAIL:-dev@feversani.internal}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"

# Si no se pasó AWS_ACCOUNT_ID, resolver automáticamente la cuenta actual de Sandbox
if [ -z "${ACCOUNT_ID}" ]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
fi

DURATION="${DURATION_MINUTES:-15}"

ENDPOINT="${ALB_URL}/api/provision-session"

echo "============================================================"
echo "🚀 Enviando POST de Aprovisionamiento JIT al Load Balancer"
echo "============================================================"
echo "📍 ALB Endpoint : ${ENDPOINT}"
echo "🗄️  Bucket S3    : ${TARGET_BUCKET}"
echo "👤 Usuario      : ${USER_NAME}"
echo "📧 Email        : ${USER_EMAIL}"
echo "⏳ Duración     : ${DURATION} minutos"
if [ -n "${ACCOUNT_ID}" ]; then
  echo "🏢 AWS Account  : ${ACCOUNT_ID} (Cross-Account)"
else
  echo "🏢 AWS Account  : Local"
fi
echo "============================================================"

# 5. Construir payload JSON
if [ -n "${ACCOUNT_ID}" ]; then
  PAYLOAD=$(cat <<EOF
{
  "bucket_name": "${TARGET_BUCKET}",
  "username": "${USER_NAME}",
  "email": "${USER_EMAIL}",
  "aws_account_id": "${ACCOUNT_ID}",
  "duration_minutes": ${DURATION}
}
EOF
)
else
  PAYLOAD=$(cat <<EOF
{
  "bucket_name": "${TARGET_BUCKET}",
  "username": "${USER_NAME}",
  "email": "${USER_EMAIL}",
  "duration_minutes": ${DURATION}
}
EOF
)
fi

echo "📦 Payload:"
echo "${PAYLOAD}"
echo "------------------------------------------------------------"

# 6. Ejecutar curl al ALB
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${ENDPOINT}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}")

HTTP_STATUS=$(echo "${RESPONSE}" | grep "HTTP_STATUS" | cut -d':' -f2)
BODY=$(echo "${RESPONSE}" | sed '/HTTP_STATUS/d')

echo "📬 HTTP Status: ${HTTP_STATUS}"
echo "📄 Respuesta:"
if command -v jq &> /dev/null; then
  echo "${BODY}" | jq .
else
  echo "${BODY}"
fi

echo "------------------------------------------------------------"
if [ "${HTTP_STATUS}" -eq 200 ] || [ "${HTTP_STATUS}" -eq 201 ]; then
  MAGIC_LINK=$(echo "${BODY}" | grep -o '"magic_link": *"[^"]*"' | cut -d'"' -f4 || true)
  if [ -n "${MAGIC_LINK}" ]; then
    echo "✨ Magic Link Generado en el ALB:"
    echo "👉 ${MAGIC_LINK}"
  fi
  echo "✅ Sesión aprovisionada exitosamente en el Load Balancer."
else
  echo "❌ Error al aprovisionar la sesión (HTTP ${HTTP_STATUS})."
  exit 1
fi
