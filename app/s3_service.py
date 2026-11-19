"""
S3 Service: Operaciones sobre S3 ejecutadas exclusivamente con las credenciales
efímeras acotadas de la sesión y auditadas en DynamoDB.
"""

import boto3
from botocore.exceptions import ClientError


class S3Service:
    def __init__(self, audit_service=None, region="us-east-1"):
        self.audit_service = audit_service
        self.region = region

    def _get_client_with_creds(self, credentials: dict):
        """
        Instancia un cliente S3 usando únicamente las credenciales temporales STS.
        """
        return boto3.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=credentials["access_key_id"],
            aws_secret_access_key=credentials["secret_access_key"],
            aws_session_token=credentials["session_token"]
        )

    def list_objects(self, bucket: str, prefix: str = "", credentials: dict = None, session_id: str = "") -> dict:
        """
        Lista objetos dentro del bucket usando las credenciales STS.
        Si las credenciales no tienen permiso sobre el bucket (e.g. forbidden-bucket),
        AWS lanzará ClientError AccessDenied (403), el cual se audita como DENIED.
        """
        s3 = self._get_client_with_creds(credentials)
        action = "ListObjectsV2"

        try:
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")
            
            # Registrar auditoría exitosa
            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, prefix, status="ALLOWED")

            prefixes = [p.get("Prefix") for p in response.get("CommonPrefixes", [])]
            objects = []
            for obj in response.get("Contents", []):
                objects.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "storage_class": obj.get("StorageClass", "STANDARD")
                })

            return {
                "bucket": bucket,
                "prefix": prefix,
                "subdirectories": prefixes,
                "objects": objects,
                "is_truncated": response.get("IsTruncated", False)
            }
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, prefix, status="DENIED", error_message=f"{error_code}: {error_msg}")
            raise e

    def get_object(self, bucket: str, key: str, credentials: dict, session_id: str = "") -> bytes:
        """
        Obtiene el contenido de un archivo usando las credenciales STS.
        """
        s3 = self._get_client_with_creds(credentials)
        action = "GetObject"

        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            content = resp["Body"].read()

            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, key, status="ALLOWED")

            return content
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, key, status="DENIED", error_message=f"{error_code}: {error_msg}")
            raise e

    def put_object(self, bucket: str, key: str, body: bytes, credentials: dict, session_id: str = ""):
        """
        Sube o actualiza un archivo usando las credenciales STS.
        """
        s3 = self._get_client_with_creds(credentials)
        action = "PutObject"

        try:
            s3.put_object(Bucket=bucket, Key=key, Body=body)

            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, key, status="ALLOWED")

            return {"status": "success", "bucket": bucket, "key": key}
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_msg = e.response["Error"]["Message"]
            if self.audit_service and session_id:
                self.audit_service.record_audit_log(session_id, action, bucket, key, status="DENIED", error_message=f"{error_code}: {error_msg}")
            raise e
