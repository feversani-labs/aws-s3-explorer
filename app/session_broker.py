"""
Session Broker: Emisión de credenciales temporales STS
acotadas dinámicamente mediante una Session Policy en línea exclusiva
para el bucket solicitado, con soporte para salto de rol multi-cuenta.
"""

import json
import os
import time
import uuid
import boto3
from botocore.exceptions import ClientError


class SessionBroker:
    def __init__(self, broker_role_arn=None, region="us-east-1"):
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.sts_client = boto3.client("sts", region_name=self.region)
        self.broker_role_arn = broker_role_arn or os.environ.get("BROKER_ROLE_ARN")

        # Auto-descubrimiento de BROKER_ROLE_ARN si no vino por variable de entorno
        if not self.broker_role_arn:
            try:
                account_id = self.sts_client.get_caller_identity().get("Account")
                role_name = os.environ.get("BROKER_ROLE_NAME", "fvrsn-sandbox-s3-broker")
                if account_id:
                    self.broker_role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
                    print(f"[SessionBroker] Auto-descubierto BROKER_ROLE_ARN: {self.broker_role_arn}")
            except Exception as e:
                print(f"[SessionBroker] No se pudo auto-descubrir BROKER_ROLE_ARN en init: {e}")

    def generate_session_policy(self, bucket_name: str) -> str:
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

    def create_ephemeral_session(self, bucket_name: str, duration_seconds: int = 900,
                                 user_identity: str = "dev-user", email: str = "",
                                 username: str = "", aws_account_id: str = "",
                                 session_id: str = None) -> dict:
        """
        Asume el BrokerRole (local o cross-account) aplicando la Session Policy generada dinámicamente.
        """
        target_role_arn = self.broker_role_arn

        # Soporte cross-account si se especifica aws_account_id
        if aws_account_id and self.broker_role_arn:
            role_name = self.broker_role_arn.split("/")[-1]
            target_role_arn = f"arn:aws:iam::{aws_account_id}:role/{role_name}"

        if not target_role_arn:
            try:
                account_id = self.sts_client.get_caller_identity().get("Account")
                role_name = os.environ.get("BROKER_ROLE_NAME", "fvrsn-sandbox-s3-broker")
                if account_id:
                    target_role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
                    self.broker_role_arn = target_role_arn
            except Exception as e:
                pass

        if not target_role_arn:
            raise ValueError("BROKER_ROLE_ARN no está configurado y falló el auto-descubrimiento.")

        token_hash = session_id or uuid.uuid4().hex
        session_name = f"s3-idp-{token_hash[:16]}"
        session_policy = self.generate_session_policy(bucket_name)

        try:
            response = self.sts_client.assume_role(
                RoleArn=target_role_arn,
                RoleSessionName=session_name,
                Policy=session_policy,
                DurationSeconds=duration_seconds
            )

            credentials = response["Credentials"]
            expires_at = int(credentials["Expiration"].timestamp())

            return {
                "session_id": token_hash,
                "target_bucket": bucket_name,
                "user_identity": user_identity or username or "dev-user",
                "email": email,
                "username": username or user_identity or "dev-user",
                "aws_account_id": aws_account_id,
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
