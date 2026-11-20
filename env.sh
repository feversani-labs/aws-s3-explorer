#!/usr/bin/env bash
# Cargar credenciales del perfil efímero en la shell actual:
# Uso: source env.sh (o . env.sh)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export AWS_PROFILE=ephemeral
export AWS_SHARED_CREDENTIALS_FILE="${SCRIPT_DIR}/.aws-credentials"
export AWS_REGION="${AWS_REGION:-us-east-1}"

echo "✅ Entorno AWS configurado:"
echo "   AWS_PROFILE=${AWS_PROFILE}"
echo "   AWS_SHARED_CREDENTIALS_FILE=${AWS_SHARED_CREDENTIALS_FILE}"
echo "   AWS_REGION=${AWS_REGION}"
