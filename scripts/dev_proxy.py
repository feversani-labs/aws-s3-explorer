#!/usr/bin/env python3
"""
Local Dev Bridge (SigV4 Proxy) for AWS Lambda Function URL
Permite abrir la aplicación en el navegador local (http://localhost:8080)
firmando automáticamente cada petición con AWS SigV4 para cumplir con
la autenticación IAM requerida por la sandbox (KodeKloud).

Zero dependencies: Usa exclusivamente la librería estándar de Python.
"""

import argparse
import configparser
import datetime
import hashlib
import hmac
import http.server
import os
import re
import socketserver
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def load_credentials(profile="ephemeral", creds_file=None):
    # 1. Variables de entorno directas
    ak = os.environ.get("AWS_ACCESS_KEY_ID")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY")
    st = os.environ.get("AWS_SESSION_TOKEN")
    if ak and sk:
        return ak, sk, st

    # 2. Archivo de credenciales
    if not creds_file:
        creds_file = os.environ.get(
            "AWS_SHARED_CREDENTIALS_FILE",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".aws-credentials")
        )

    if os.path.exists(creds_file):
        config = configparser.ConfigParser()
        config.read(creds_file)
        if profile in config:
            section = config[profile]
            return (
                section.get("aws_access_key_id"),
                section.get("aws_secret_access_key"),
                section.get("aws_session_token"),
            )
        elif "default" in config:
            section = config["default"]
            return (
                section.get("aws_access_key_id"),
                section.get("aws_secret_access_key"),
                section.get("aws_session_token"),
            )

    raise ValueError(
        f"No se encontraron credenciales AWS en variables de entorno ni en {creds_file} (perfil: {profile})"
    )


def get_lambda_url_from_tf():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tf_dir = os.path.join(base_dir, "terraform")
    try:
        res = subprocess.run(
            ["terraform", "output", "-raw", "lambda_function_url"],
            cwd=tf_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        url = res.stdout.strip()
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return None


def sign_hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(key, date_stamp, region_name, service_name):
    k_date = sign_hmac(("AWS4" + key).encode("utf-8"), date_stamp)
    k_region = sign_hmac(k_date, region_name)
    k_service = sign_hmac(k_region, service_name)
    return sign_hmac(k_service, "aws4_request")


def create_proxy_handler(target_url, access_key, secret_key, session_token, region):
    parsed_target = urllib.parse.urlparse(target_url)
    target_host = parsed_target.netloc

    class SigV4ProxyHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Log limpio con timestamp
            sys.stdout.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {args[0]} -> {args[1]}\n")
            sys.stdout.flush()

        def do_request(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b""

            # Payload hash
            payload_hash = hashlib.sha256(body).hexdigest()

            # Fecha y timestamp
            t = datetime.datetime.now(datetime.timezone.utc)
            amz_date = t.strftime("%Y%m%dT%H%M%SZ")
            date_stamp = t.strftime("%Y%m%d")

            # Construir path y query
            path_parts = self.path.split("?", 1)
            canonical_uri = urllib.parse.quote(path_parts[0], safe="/~")
            canonical_querystring = ""
            if len(path_parts) > 1:
                query_params = urllib.parse.parse_qsl(path_parts[1], keep_blank_values=True)
                query_params.sort(key=lambda x: x[0])
                canonical_querystring = urllib.parse.urlencode(query_params)

            # Canonical headers requeridos para SigV4
            headers_to_sign = {
                "host": target_host,
                "x-amz-date": amz_date,
                "x-amz-content-sha256": payload_hash,
            }
            if session_token:
                headers_to_sign["x-amz-security-token"] = session_token

            # Propagar Content-Type si viene del cliente
            content_type = self.headers.get("Content-Type")
            if content_type:
                headers_to_sign["content-type"] = content_type

            # Ordenar headers canónicos
            sorted_header_keys = sorted(headers_to_sign.keys())
            canonical_headers = "".join([f"{k}:{headers_to_sign[k]}\n" for k in sorted_header_keys])
            signed_headers = ";".join(sorted_header_keys)

            # Canonical request
            canonical_request = (
                f"{self.command}\n"
                f"{canonical_uri}\n"
                f"{canonical_querystring}\n"
                f"{canonical_headers}\n"
                f"{signed_headers}\n"
                f"{payload_hash}"
            )

            # String to sign
            algorithm = "AWS4-HMAC-SHA256"
            credential_scope = f"{date_stamp}/{region}/lambda/aws4_request"
            string_to_sign = (
                f"{algorithm}\n"
                f"{amz_date}\n"
                f"{credential_scope}\n"
                f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
            )

            # Calcular firma
            signing_key = get_signature_key(secret_key, date_stamp, region, "lambda")
            signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

            authorization_header = (
                f"{algorithm} Credential={access_key}/{credential_scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            )

            # Preparar request hacia la Lambda Function URL
            dest_url = f"{parsed_target.scheme}://{target_host}{canonical_uri}"
            if canonical_querystring:
                dest_url += f"?{canonical_querystring}"

            req = urllib.request.Request(dest_url, data=body if body else None, method=self.command)
            req.add_header("Host", target_host)
            req.add_header("x-amz-date", amz_date)
            req.add_header("x-amz-content-sha256", payload_hash)
            req.add_header("Authorization", authorization_header)
            if session_token:
                req.add_header("x-amz-security-token", session_token)
            if content_type:
                req.add_header("Content-Type", content_type)

            # Reenviar otros headers útiles (Accept, etc.)
            for header_key in ["Accept", "Accept-Language", "User-Agent"]:
                val = self.headers.get(header_key)
                if val:
                    req.add_header(header_key, val)

            # Ejecutar llamada
            try:
                with urllib.request.urlopen(req) as resp:
                    resp_body = resp.read()
                    self.send_response(resp.status)
                    for k, v in resp.getheaders():
                        # Omitir headers de transferencia conflictivos
                        if k.lower() not in ["transfer-encoding", "content-length", "connection"]:
                            self.send_header(k, v)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
            except urllib.error.HTTPError as e:
                err_body = e.read()
                self.send_response(e.code)
                for k, v in e.headers.items():
                    if k.lower() not in ["transfer-encoding", "content-length", "connection"]:
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
            except Exception as e:
                err_msg = f"Error al reenviar a Lambda: {str(e)}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(err_msg)))
                self.end_headers()
                self.wfile.write(err_msg)

        do_GET = do_request
        do_POST = do_request
        do_PUT = do_request
        do_DELETE = do_request
        do_OPTIONS = do_request
        do_HEAD = do_request

    return SigV4ProxyHandler


def main():
    parser = argparse.ArgumentParser(description="Local SigV4 Proxy para Lambda Function URL")
    parser.add_argument("--url", help="URL de la Lambda (ej: https://xxx.lambda-url.us-east-1.on.aws/)")
    parser.add_argument("--port", type=int, default=8080, help="Puerto local (default: 8080)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"), help="Región AWS")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE", "ephemeral"), help="Perfil AWS en .aws-credentials")
    args = parser.parse_args()

    # 1. Obtener URL
    target_url = args.url or os.environ.get("LAMBDA_URL")
    if not target_url:
        print("[Dev Bridge] Buscando URL de Lambda en terraform output...")
        target_url = get_lambda_url_from_tf()

    if not target_url:
        print("\n[ERROR] No se pudo determinar la URL de la Lambda.")
        print("Asegurate de haber ejecutado 'terraform apply' o pasá la URL con --url <URL>\n")
        sys.exit(1)

    # 2. Cargar credenciales
    try:
        ak, sk, st = load_credentials(profile=args.profile)
    except Exception as e:
        print(f"\n[ERROR] {e}\n")
        sys.exit(1)

    # Detectar región si está en la URL
    match_region = re.search(r"lambda-url\.([a-z0-9-]+)\.on\.aws", target_url)
    region = match_region.group(1) if match_region else args.region

    # 3. Iniciar servidor
    handler_class = create_proxy_handler(target_url, ak, sk, st, region)
    
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    with ReusableTCPServer(("127.0.0.1", args.port), handler_class) as httpd:
        print("=" * 65)
        print(" 🚀 S3 EXPLORER — LOCAL DEV BRIDGE (SIGV4 PROXY)")
        print("=" * 65)
        print(f" Target Lambda URL : {target_url}")
        print(f" AWS Profile       : {args.profile}")
        print(f" AWS Region        : {region}")
        print(f" Acceso Web Local  : http://localhost:{args.port}")
        print("-" * 65)
        print(" Abrí http://localhost:{0} en tu navegador para interactuar con la app.".format(args.port))
        print(" Presioná Ctrl+C para detener el bridge.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[Dev Bridge] Detenido por el usuario.")


if __name__ == "__main__":
    main()
