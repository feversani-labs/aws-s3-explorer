"""
Audit Service: Registro Fail-Closed de sesiones y acciones sobre S3
en DynamoDB con soporte multi-cuenta y auditoría enriquecida.
"""

import os
import time
import boto3
from botocore.exceptions import ClientError


class AuditService:
    def __init__(self, table_name=None, region="us-east-1"):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.table_name = table_name or os.environ.get("DYNAMODB_TABLE") or "fvrsn-sandbox-s3-explorer-idp"
        self.dynamodb = boto3.resource("dynamodb", region_name=self.region)
        self.table = self.dynamodb.Table(self.table_name) if self.table_name else None

    def record_session(self, session_data: dict):
        """
        Registra la creación de una sesión efímera.
        Incluye email, username, aws_account_id y TTL en 'expires_at'.
        """
        if not self.table:
            return

        item = {
            "PK": f"SESSION#{session_data['session_id']}",
            "SK": "METADATA",
            "session_id": session_data["session_id"],
            "target_bucket": session_data["target_bucket"],
            "aws_account_id": session_data.get("aws_account_id", ""),
            "email": session_data.get("email", ""),
            "username": session_data.get("username", "dev-user"),
            "assumed_role_arn": session_data.get("assumed_role_arn", ""),
            "credentials": session_data.get("credentials", {}),
            "created_at": int(time.time()),
            "expires_at": int(session_data["expires_at"])
        }

        try:
            self.table.put_item(Item=item)
            # Registrar también en el historial de auditoría
            self.record_audit_log(
                session_id=session_data["session_id"],
                action="sts:AssumeRole",
                bucket=session_data["target_bucket"],
                email=session_data.get("email", ""),
                username=session_data.get("username", "dev-user"),
                aws_account_id=session_data.get("aws_account_id", ""),
                status="ALLOWED"
            )
        except ClientError as e:
            raise RuntimeError(f"Fail-Closed: no se pudo registrar la sesión en DynamoDB: {e.response['Error']['Message']}")

    def get_session(self, session_id: str):
        """
        Recupera la sesión y credenciales desde DynamoDB.
        """
        if not self.table:
            return None
        try:
            resp = self.table.get_item(Key={
                "PK": f"SESSION#{session_id}",
                "SK": "METADATA"
            })
            item = resp.get("Item")
            if item:
                if "expires_at" in item:
                    item["expires_at"] = int(item["expires_at"])
                if "created_at" in item:
                    item["created_at"] = int(item["created_at"])
            return item
        except Exception as e:
            print(f"[AuditService] get_session error: {e}")
            return None

    def record_audit_log(self, session_id: str, action: str, bucket: str, key: str = "",
                         email: str = "", username: str = "", aws_account_id: str = "",
                         status: str = "ALLOWED", error_message: str = ""):
        """
        Registra cada operación ejecutada con correo, usuario, cuenta y bucket.
        """
        if not self.table:
            return

        now = int(time.time())
        ttl = now + 86400  # Expira en 24h

        item = {
            "PK": f"SESSION#{session_id}",
            "SK": f"AUDIT#{now}#{action}",
            "session_id": session_id,
            "action": action,
            "bucket": bucket,
            "key": key,
            "email": email,
            "username": username,
            "aws_account_id": aws_account_id,
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
            resp = self.table.scan(Limit=limit)
            items = resp.get("Items", [])
            audit_items = [i for i in items if str(i.get("SK", "")).startswith("AUDIT#")]
            audit_items.sort(key=lambda x: int(x.get("timestamp", 0)), reverse=True)
            return audit_items
        except Exception as e:
            print(f"[AuditService] scan error: {e}")
            return []
