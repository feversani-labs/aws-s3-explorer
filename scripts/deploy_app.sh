#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export AWS_PROFILE="${AWS_PROFILE:-ephemeral}"
export AWS_SHARED_CREDENTIALS_FILE="${AWS_SHARED_CREDENTIALS_FILE:-$ROOT_DIR/.aws-credentials}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

echo "==> Buscando nombre de la función Lambda..."
LAMBDA_NAME=$(aws ssm get-parameter --name "/ephemeral-aws-sandbox/s3-explorer/lambda-name" --query 'Parameter.Value' --output text 2>/dev/null || true)

if [ -z "$LAMBDA_NAME" ]; then
    echo "No se encontró el parámetro SSM, intentando via terraform output..."
    LAMBDA_NAME=$(cd "$ROOT_DIR/terraform" && terraform output -raw lambda_function_url 2>/dev/null | sed -E 's|https://([^.]+).*|\1|' || true)
fi

if [ -z "$LAMBDA_NAME" ]; then
    echo "ERROR: No se pudo obtener el nombre de la Lambda. Asegurate de haber hecho 'make apply' primero."
    exit 1
fi

echo "==> Empaquetando aplicación (app/)..."
BUILD_DIR="$ROOT_DIR/build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Si existen dependencias en requirements.txt y no están vacías, se instalan en el paquete
if [ -f "$ROOT_DIR/requirements.txt" ] && [ -s "$ROOT_DIR/requirements.txt" ]; then
    echo "==> Instalando dependencias desde requirements.txt..."
    pip install -r "$ROOT_DIR/requirements.txt" -t "$BUILD_DIR/package" --platform manylinux2014_x86_64 --only-binary=:all: || \
    pip install -r "$ROOT_DIR/requirements.txt" -t "$BUILD_DIR/package"
    cp -r "$ROOT_DIR/app/"* "$BUILD_DIR/package/"
    (cd "$BUILD_DIR/package" && zip -r9 "$BUILD_DIR/lambda.zip" .)
else
    (cd "$ROOT_DIR/app" && zip -r9 "$BUILD_DIR/lambda.zip" .)
fi

echo "==> Desplegando en AWS Lambda: $LAMBDA_NAME..."
aws lambda update-function-code \
    --function-name "$LAMBDA_NAME" \
    --zip-file "fileb://$BUILD_DIR/lambda.zip" \
    --output json > /dev/null

echo "==> Esperando confirmación de actualización..."
aws lambda wait function-updated --function-name "$LAMBDA_NAME"

echo "✅ Despliegue completado exitosamente!"
