"""
Audit Service: Registro Fail-Closed de sesiones y acciones sobre S3
en DynamoDB con TTL automático.
"""

import os
import time
import boto3
from botocore.exceptions import ClientError


class AuditService:
    def __init__(self, table_name=None, region="us-east-1"):
        self.table_name = table_name or os.environ.get("DYNAMODB_TABLE")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.table = self.dynamodb.Table(self.table_name) if self.table_name else None

    def record_session(self, session_data: dict):
        """
        Registra la creación de una sesión efímera.
        Incluye TTL en 'expires_at'.
        """
        if not self.table:
            return

        item = {
            "PK": f"SESSION#{session_data['session_id']}",
            "SK": "METADATA",
            "session_id": session_data["session_id"],
            "target_bucket": session_data["target_bucket"],
            "user_identity": session_data.get("user_identity", "dev-user"),
            "assumed_role_arn": session_data.get("assumed_role_arn", ""),
            "created_at": int(time.time()),
            "expires_at": session_data["expires_at"]
        }

        try:
            self.table.put_item(Item=item)
        except ClientError as e:
            # En modo Fail-Closed, si falla la auditoría, la sesión no debe proceder
            raise RuntimeError(f"Fail-Closed: no se pudo registrar la sesión en DynamoDB: {e.response['Error']['Message']}")

    def record_audit_log(self, session_id: str, action: str, bucket: str, key: str = "", status: str = "ALLOWED", error_message: str = ""):
        """
        Registra cada operación ejecutada (ListObjects, GetObject, PutObject, etc.)
        y su resultado (ALLOWED o DENIED).
        """
        if not self.table:
            return

        now = int(time.time())
        # El log de auditoría expira 24 horas después de la sesión
        ttl = now + 86400

        item = {
            "PK": f"SESSION#{session_id}",
            "SK": f"AUDIT#{now}#{action}",
            "action": action,
            "bucket": bucket,
            "key": key,
            "status": status,
            "error_message": error_message,
            "timestamp": now,
            "expires_at": ttl
        }

        try:
            self.table.put_item(Item=item)
        except ClientError as e:
            raise RuntimeError(f"Fail-Closed: error al registrar auditoría en DynamoDB: {e.response['Error']['Message']}")

    def get_recent_audits(self, limit: int = 50) -> list:
        """
        Recupera los últimos registros de auditoría si la tabla existe.
        """
        if not self.table:
            return []

        try:
            # Escaneo simple limitado para la vista de auditoría del dashboard
            resp = self.table.scan(Limit=limit)
            items = resp.get("Items", [])
            # Filtrar solo entradas de auditoría y ordenar por timestamp descendente
            audit_items = [i for i in items if i.get("SK", "").startswith("AUDIT#")]
            audit_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return audit_items
        except Exception:
            return []
