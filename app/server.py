"""
Servidor HTTP autónomo para S3 Explorer IDP (Docker / EC2).
Soporta aprovisionamiento via Webhook POST, Magic Links (?session=UUID),
salto de rol multi-cuenta y auditoría enriquecida.
"""

import decimal
import json
import os
import sys
import time
import urllib.parse
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from botocore.exceptions import ClientError

from session_broker import SessionBroker
from audit_service import AuditService
from s3_service import S3Service

ACTIVE_SESSIONS = {}

audit_service = AuditService()
session_broker = SessionBroker()
s3_service = S3Service(audit_service=audit_service)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def load_static_index():
    static_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(static_path):
        with open(static_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>S3 Explorer IDP</h1><p>UI no encontrada en static/index.html</p>"


def get_active_session(session_id: str):
    if not session_id:
        return None
    session_data = ACTIVE_SESSIONS.get(session_id)
    if not session_data:
        session_data = audit_service.get_session(session_id)
        if session_data:
            ACTIVE_SESSIONS[session_id] = session_data
    return session_data


class S3ExplorerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stdout.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {args[0]} -> {args[1]}\n")
        sys.stdout.flush()

    def _send_response(self, status_code: int, body, content_type: str = "application/json"):
        if isinstance(body, (dict, list)):
            payload = json.dumps(body, cls=DecimalEncoder).encode("utf-8")
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        elif isinstance(body, bytes):
            payload = body
        else:
            payload = str(body).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Session-ID,Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send_response(200, {"status": "ok"})

    def _parse_url(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return path, query

    def _read_body_json(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def do_GET(self):
        path, query = self._parse_url()

        # 1. UI Web
        if path == "/" or path == "/index.html":
            return self._send_response(200, load_static_index(), content_type="text/html; charset=utf-8")

        # 2. Información del entorno
        if path == "/api/info":
            broker_arn = session_broker.broker_role_arn or os.environ.get("BROKER_ROLE_ARN", "")
            enable_sandbox = os.environ.get("ENABLE_SANDBOX", os.environ.get("MODE", "true")).lower() in ["true", "1", "yes", "sandbox"]
            return self._send_response(200, {
                "status": "ready",
                "enable_sandbox": enable_sandbox,
                "mode": "sandbox" if enable_sandbox else "prod",
                "broker_role_configured": bool(broker_arn),
                "broker_role_arn": broker_arn,
                "dynamodb_configured": bool(audit_service.table_name),
                "dynamodb_table": audit_service.table_name,
                "default_account_id": os.environ.get("DEFAULT_ACCOUNT_ID", ""),
                "default_bucket": os.environ.get("DEFAULT_BUCKET", "")
            })

        # 3. Validar sesión desde Magic Link (?session=hash)
        if path == "/api/sessions/validate":
            session_id = query.get("session") or self.headers.get("X-Session-ID")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(404, {"error": "Sesión inválida o expirada"})

            now = int(time.time())
            remaining = int(session_data.get("expires_at", 0)) - now
            if remaining <= 0:
                return self._send_response(410, {"error": "Sesión expirada", "remaining_seconds": 0})

            return self._send_response(200, {
                "session_id": session_data["session_id"],
                "target_bucket": session_data["target_bucket"],
                "email": session_data.get("email", ""),
                "username": session_data.get("username", ""),
                "aws_account_id": session_data.get("aws_account_id", ""),
                "expires_at": session_data["expires_at"],
                "remaining_seconds": remaining
            })

        # 4. Listar objetos S3
        if path == "/api/objects":
            session_id = self.headers.get("X-Session-ID") or query.get("session_id")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(401, {"error": "Sesión inválida o expirada"})

            prefix = query.get("prefix", "")
            try:
                result = s3_service.list_objects(
                    bucket=session_data["target_bucket"],
                    prefix=prefix,
                    credentials=session_data["credentials"],
                    session_id=session_id,
                    session_meta=session_data
                )
                return self._send_response(200, result)
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return self._send_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # 5. Descargar / Ver contenido de objeto
        if path == "/api/objects/content":
            session_id = self.headers.get("X-Session-ID") or query.get("session_id")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(401, {"error": "Sesión inválida o expirada"})

            key = query.get("key", "")
            if not key:
                return self._send_response(400, {"error": "key es requerida"})

            try:
                content = s3_service.get_object(
                    bucket=session_data["target_bucket"],
                    key=key,
                    credentials=session_data["credentials"],
                    session_id=session_id,
                    session_meta=session_data
                )
                return self._send_response(200, content, content_type="text/plain; charset=utf-8")
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return self._send_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # 6. Registros de auditoría
        if path == "/api/audits":
            items = audit_service.get_recent_audits(limit=50)
            return self._send_response(200, {"items": items})

        return self._send_response(404, {"error": "Not Found"})

    def do_POST(self):
        path, query = self._parse_url()

        # Aprovisionamiento via Webhook POST /api/provision-session o /api/sessions
        if path in ["/api/provision-session", "/api/sessions"]:
            data = self._read_body_json()
            bucket_name = data.get("bucket_name")
            email = data.get("email", "")
            username = data.get("username", "dev-user")
            aws_account_id = data.get("aws_account_id", "")
            duration_minutes = int(data.get("duration_minutes", 15))
            duration_seconds = max(900, duration_minutes * 60)

            if not bucket_name:
                return self._send_response(400, {"error": "bucket_name es obligatorio"})

            try:
                session_hash = uuid.uuid4().hex
                session_data = session_broker.create_ephemeral_session(
                    bucket_name=bucket_name,
                    duration_seconds=duration_seconds,
                    user_identity=username,
                    email=email,
                    username=username,
                    aws_account_id=aws_account_id,
                    session_id=session_hash
                )

                ACTIVE_SESSIONS[session_hash] = session_data
                audit_service.record_session(session_data)

                # Construir el Magic Link
                host = self.headers.get("Host", "localhost:8080")
                magic_link = f"http://{host}/?session={session_hash}"

                return self._send_response(201, {
                    "status": "created",
                    "session_id": session_hash,
                    "magic_link": magic_link,
                    "target_bucket": bucket_name,
                    "email": email,
                    "username": username,
                    "aws_account_id": aws_account_id,
                    "expires_at": session_data["expires_at"],
                    "duration_minutes": duration_minutes
                })
            except Exception as e:
                return self._send_response(500, {"error": "Error al aprovisionar sesión", "message": str(e)})

        # Operaciones CRUD sobre S3: Crear / Actualizar objeto
        if path == "/api/objects/upload":
            session_id = self.headers.get("X-Session-ID") or query.get("session_id")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(401, {"error": "Sesión inválida o expirada"})

            data = self._read_body_json()
            key = data.get("key", "").strip().lstrip("/")
            content = data.get("content", "")
            if not key:
                return self._send_response(400, {"error": "El nombre del archivo (key) es requerido"})

            try:
                body_bytes = content.encode("utf-8") if isinstance(content, str) else content
                s3_service.put_object(
                    bucket=session_data["target_bucket"],
                    key=key,
                    body=body_bytes,
                    credentials=session_data["credentials"],
                    session_id=session_id,
                    session_meta=session_data
                )
                return self._send_response(200, {"status": "success", "message": f"Archivo '{key}' guardado exitosamente"})
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return self._send_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # Operaciones CRUD sobre S3: Eliminar objeto
        if path == "/api/objects/delete":
            session_id = self.headers.get("X-Session-ID") or query.get("session_id")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(401, {"error": "Sesión inválida o expirada"})

            data = self._read_body_json()
            key = data.get("key", "").strip()
            if not key:
                return self._send_response(400, {"error": "El nombre del archivo (key) es requerido"})

            try:
                s3_service.delete_object(
                    bucket=session_data["target_bucket"],
                    key=key,
                    credentials=session_data["credentials"],
                    session_id=session_id,
                    session_meta=session_data
                )
                return self._send_response(200, {"status": "success", "message": f"Archivo '{key}' eliminado exitosamente"})
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return self._send_response(403 if code == "AccessDenied" else 500, {
                    "error": code,
                    "message": e.response["Error"]["Message"]
                })

        # Prueba de acceso a bucket prohibido
        if path == "/api/test-forbidden":
            session_id = self.headers.get("X-Session-ID") or query.get("session_id")
            session_data = get_active_session(session_id)
            if not session_data:
                return self._send_response(401, {"error": "Sesión inválida o expirada"})

            forbidden_bucket = f"forbidden-bucket-test-9999"

            try:
                s3_service.list_objects(
                    bucket=forbidden_bucket,
                    prefix="",
                    credentials=session_data["credentials"],
                    session_id=session_id,
                    session_meta=session_data
                )
                return self._send_response(200, {"status": "UNEXPECTED_ALLOW", "message": "Frontera rota"})
            except ClientError as e:
                code = e.response["Error"]["Code"]
                return self._send_response(403, {
                    "status": "DENIED",
                    "code": code,
                    "message": f"AWS STS Session Policy bloqueó el acceso como se esperaba: {e.response['Error']['Message']}"
                })

        return self._send_response(404, {"error": "Not Found"})


def run_server(port=8080):
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, S3ExplorerHandler)
    print("=" * 60)
    print(f" 🚀 S3 EXPLORER IDP RUNNING ON PORT {port}")
    print(f" Broker Role : {os.environ.get('BROKER_ROLE_ARN', 'None')}")
    print(f" DynamoDB    : {os.environ.get('DYNAMODB_TABLE', 'None')}")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_server(port=port)
