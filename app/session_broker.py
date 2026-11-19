"""
Session Broker: Emisión de credenciales temporales STS
acotadas dinámicamente mediante una Session Policy en línea exclusiva
para el bucket solicitado (Principio de Mínimo Privilegio - Just-In-Time).
"""

import json
import os
import time
import boto3
from botocore.exceptions import ClientError


class SessionBroker:
    def __init__(self, broker_role_arn=None, region="us-east-1"):
        self.broker_role_arn = broker_role_arn or os.environ.get("BROKER_ROLE_ARN")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.sts_client = boto3.client("sts", region_name=self.region)

    def generate_session_policy(self, bucket_name: str) -> str:
        """
        Genera la Session Policy en línea estricta que recorta
        los permisos del BrokerRole únicamente al bucket especificado.
        Cualquier intento de acceder a otro bucket (incluso si el BrokerRole
        lo permite como techo) será denegado por STS.
        """
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowListSpecificBucket",
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": [f"arn:aws:s3:::{bucket_name}"]
                },
                {
                    "Sid": "AllowReadWriteSpecificBucketObjects",
                    "Effect": "Allow",
                    "Action": [
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject"
                    ],
                    "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                }
            ]
        }
        return json.dumps(policy)

    def create_ephemeral_session(self, bucket_name: str, duration_seconds: int = 900, user_identity: str = "dev-user") -> dict:
        """
        Asume el BrokerRole aplicando la Session Policy generada dinámicamente.
        Duración por defecto: 900 segundos (15 minutos, mínimo soportado por STS).
        """
        if not self.broker_role_arn:
            raise ValueError("BROKER_ROLE_ARN no está configurado en las variables de entorno.")

        session_name = f"s3-idp-{int(time.time())}"
        session_policy = self.generate_session_policy(bucket_name)

        try:
            response = self.sts_client.assume_role(
                RoleArn=self.broker_role_arn,
                RoleSessionName=session_name,
                Policy=session_policy,
                DurationSeconds=duration_seconds,
                Tags=[
                    {"Key": "CreatedBy", "Value": user_identity},
                    {"Key": "TargetBucket", "Value": bucket_name}
                ]
            )

            credentials = response["Credentials"]
            expires_at = int(credentials["Expiration"].timestamp())

            return {
                "session_id": session_name,
                "target_bucket": bucket_name,
                "user_identity": user_identity,
                "assumed_role_arn": response["AssumedRoleUser"]["Arn"],
                "expires_at": expires_at,
                "duration_seconds": duration_seconds,
                "credentials": {
                    "access_key_id": credentials["AccessKeyId"],
                    "secret_access_key": credentials["SecretAccessKey"],
                    "session_token": credentials["SessionToken"],
                    "expiration": credentials["Expiration"].isoformat()
                }
            }
        except ClientError as e:
            raise RuntimeError(f"Error al asumir rol en STS: {e.response['Error']['Message']}")
