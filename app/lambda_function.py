"""
Punto de entrada de AWS Lambda (Function URL / API Gateway v2).
Enruta las peticiones HTTP hacia el Session Broker, S3 Service y Audit Service,
y sirve la interfaz web de autoservicio.
"""

import base64
import json
import os
import urllib.parse
from botocore.exceptions import ClientError

from session_broker import SessionBroker
from audit_service import AuditService
from s3_service import S3Service

# Cache de sesiones activas en la memoria de la instancia Lambda
ACTIVE_SESSIONS = {}

audit_service = AuditService()
session_broker = SessionBroker()
s3_service = S3Service(audit_service=audit_service)


def load_static_index():
    static_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_path):
        with open(static_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>S3 Explorer IDP</h1><p>UI no encontrada en static/index.html</p>"


def build_response(status_code: int, body, content_type: str = "application/json"):
    headers = {
        "Content-Type": content_type,
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,X-Session-ID,X-API-Key,Authorization",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
    }

    if isinstance(body, (dict, list)):
        payload = json.dumps(body)
    elif isinstance(body, bytes):
        payload = body.decode("utf-8", errors="replace")
    else:
        payload = str(body)

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": payload
    }


def parse_body(event):
    body = event.get("body", "")
    if not body:
        return {}
    if event.get("isBase64Encoded", False):
        body = base64.b64decode(body).decode("utf-8")
    try:
        return json.loads(body)
    except Exception:
        return {}


def handler(event, context):
    # Soporte para Lambda Function URL (formato payload v2) y invocaciones locales
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET").upper()
    path = event.get("rawPath", "/")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    query_params = event.get("queryStringParameters") or {}

    # Manejo de Preflight CORS (OPTIONS)
    if method == "OPTIONS":
        return build_response(200, {"status": "ok"})

    try:
        # 1. UI Web
        if path == "/" or path == "/index.html":
            return build_response(200, load_static_index(), content_type="text/html; charset=utf-8")

        # 2. Información del entorno
        if path == "/api/info" and method == "GET":
            broker_role = os.environ.get("BROKER_ROLE_ARN", "")
            dynamo_table = os.environ.get("DYNAMODB_TABLE", "")
            return build_response(200, {
                "status": "ready" if broker_role else "waiting_infra",
                "mode": os.environ.get("MODE", "sandbox"),
                "broker_role_configured": bool(broker_role),
                "dynamodb_configured": bool(dynamo_table),
                "default_bucket": os.environ.get("DEFAULT_BUCKET", "")
            })

        # 3. Crear sesión efímera con STS Session Policy
        if path == "/api/sessions" and method == "POST":
            data = parse_body(event)
            bucket_name = data.get("bucket_name")
            duration = int(data.get("duration_seconds", 900))

            if not bucket_name:
                return build_response(400, {"error": "bucket_name es obligatorio"})

            if not os.environ.get("BROKER_ROLE_ARN"):
                return build_response(503, {
                    "error": "BROKER_ROLE_ARN no configurado en la Lambda.",
                    "message": "Falta desplegar el BrokerRole en Terraform y agregarlo a las variables de entorno de la Lambda."
                })

            session_data = session_broker.create_ephemeral_session(
                bucket_name=bucket_name,
                duration_seconds=duration,
                user_identity=headers.get("x-user-identity", "dev-user")
            )

            # Guardar en cache y registrar en DynamoDB
            ACTIVE_SESSIONS[session_data["session_id"]] = session_data
            audit_service.record_session(session_data)

            # Devolver metadata de la sesión (sin exponer el secret key al cliente web)
            return build_response(201, {
                "session_id": session_data["session_id"],
                "target_bucket": session_data["target_bucket"],
                "expires_at": session_data["expires_at"],
                "duration_seconds": session_data["duration_seconds"],
                "assumed_role_arn": session_data["assumed_role_arn"]
            })

        # 4. Listar objetos usando las credenciales STS de la sesión
        if path == "/api/objects" and method == "GET":
            session_id = headers.get("x-session-id")
            if not session_id or session_id not in ACTIVE_SESSIONS:
                return build_response(401, {"error": "Sesión inválida o expirada. Solicitá una nueva sesión."})

            session_data = ACTIVE_SESSIONS[session_id]
            prefix = query_params.get("prefix", "")

            try:
                result = s3_service.list_objects(
                    bucket=session_data["target_bucket"],
                    prefix=prefix,
                    credentials=session_data["credentials"],
                    session_id=session_id
                )
                return build_response(200, result)
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return build_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # 5. Obtener contenido de un objeto
        if path == "/api/objects/content" and method == "GET":
            session_id = headers.get("x-session-id")
            if not session_id or session_id not in ACTIVE_SESSIONS:
                return build_response(401, {"error": "Sesión inválida o expirada"})

            session_data = ACTIVE_SESSIONS[session_id]
            key = query_params.get("key", "")
            if not key:
                return build_response(400, {"error": "key es requerida"})

            try:
                content = s3_service.get_object(
                    bucket=session_data["target_bucket"],
                    key=key,
                    credentials=session_data["credentials"],
                    session_id=session_id
                )
                return build_response(200, content, content_type="text/plain; charset=utf-8")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return build_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # 6. Prueba de frontera de seguridad (acceso a bucket prohibido)
        if path == "/api/test-forbidden" and method == "POST":
            session_id = headers.get("x-session-id")
            if not session_id or session_id not in ACTIVE_SESSIONS:
                return build_response(401, {"error": "Sesión inválida o expirada"})

            session_data = ACTIVE_SESSIONS[session_id]
            forbidden_bucket = f"forbidden-bucket-test-{int(os.environ.get('FORBIDDEN_SUFFIX', 9999))}"

            try:
                # Intentar listar con la misma sesión acotada
                s3_service.list_objects(
                    bucket=forbidden_bucket,
                    prefix="",
                    credentials=session_data["credentials"],
                    session_id=session_id
                )
                # Si llega acá, falló la frontera
                return build_response(200, {"status": "UNEXPECTED_ALLOW", "message": "Frontera rota: el acceso debió ser denegado."})
            except ClientError as e:
                # Esperado: 403 AccessDenied
                code = e.response["Error"]["Code"]
                return build_response(403, {
                    "status": "DENIED",
                    "code": code,
                    "message": f"AWS STS Session Policy bloqueó el acceso como se esperaba: {e.response['Error']['Message']}"
                })

        # 7. Recuperar registros de auditoría de DynamoDB
        if path == "/api/audits" and method == "GET":
            items = audit_service.get_recent_audits(limit=25)
            return build_response(200, {"items": items})

        return build_response(404, {"error": f"Ruta no encontrada: {method} {path}"})

    except Exception as e:
        return build_response(500, {"error": "InternalServerError", "message": str(e)})
