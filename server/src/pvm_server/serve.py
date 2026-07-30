#!/usr/bin/env python3
"""Small production-shaped reference module service using immutable module URLs."""

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .compiler import CompileError
from .manifest import decode_envelope


class ModuleHandler(BaseHTTPRequestHandler):
    server_version = "PVMModuleService/0.2"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.request_timeout)

    def handle_one_request(self):
        self.request_id = secrets.token_hex(16)
        super().handle_one_request()

    def _send(self, status, body=b"", content_type="application/json", headers=None):
        headers = headers or {}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("X-PVM-Request-ID", self.request_id)
        if "Cache-Control" not in headers:
            self.send_header("Cache-Control", "no-store")
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, message):
        self._send(status, (json.dumps({"error": message}) + "\n").encode("utf-8"))

    def _authorized(self):
        expected = self.server.activation_token
        if not expected:
            return self.server.allow_unauthenticated
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(supplied[len(prefix) :], expected)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self._send(405, b'{"error":"method not allowed"}\n', headers={"Allow": "GET, HEAD"})

    do_DELETE = do_POST
    do_PATCH = do_POST
    do_PUT = do_POST

    def do_GET(self):
        raw_path = unquote(urlparse(self.path).path)
        parts = [part for part in raw_path.split("/") if part]
        if parts in (["healthz"], ["livez"]):
            self._send(200, b'{"status":"ok"}\n')
            return
        if parts == ["readyz"]:
            ready = self.server.repository.is_dir()
            self._send(
                200 if ready else 503,
                b'{"status":"ready"}\n' if ready else b'{"status":"unavailable"}\n',
            )
            return
        if len(parts) == 7 and parts[:2] == ["v1", "apps"] and parts[6] == "manifest":
            _, _, app_id, channel, platform, profile, _ = parts
            if (
                not self._safe_segment(app_id)
                or not self._safe_segment(channel)
                or platform not in ("android", "ios", "harmonyos", "desktop")
                or profile
                not in (
                    "offline_sealed",
                    "online_provisioned",
                    "store_on_demand",
                    "enterprise_managed",
                )
            ):
                self._error(404, "invalid manifest path")
                return
            if profile in ("online_provisioned", "enterprise_managed") and not self._authorized():
                self._error(401, "activation required")
                return
            manifest = (
                self.server.repository
                / "apps"
                / app_id
                / channel
                / platform
                / profile
                / "manifest.json"
            )
            self._serve_manifest(manifest)
            return
        if len(parts) == 6 and parts[:2] == ["v1", "apps"] and parts[5] == "manifest":
            # Read-only compatibility with the pre-platform route; ambiguous repositories fail.
            _, _, app_id, channel, profile, _ = parts
            if (
                not self._safe_segment(app_id)
                or not self._safe_segment(channel)
                or profile
                not in (
                    "offline_sealed",
                    "online_provisioned",
                    "store_on_demand",
                    "enterprise_managed",
                )
            ):
                self._error(404, "invalid manifest path")
                return
            base = self.server.repository / "apps" / app_id / channel
            legacy = base / profile / "manifest.json"
            matches = [legacy] if legacy.is_file() else list(base.glob("*/%s/manifest.json" % profile))
            if len(matches) != 1:
                self._error(409, "legacy route is ambiguous; include platform")
                return
            if profile in ("online_provisioned", "enterprise_managed") and not self._authorized():
                self._error(401, "activation required")
                return
            self._serve_manifest(matches[0])
            return
        if len(parts) == 3 and parts[:2] == ["v1", "modules"]:
            self._serve_module(parts[2])
            return
        self._error(404, "not found")

    @staticmethod
    def _safe_segment(value):
        return (
            0 < len(value) <= 255
            and value not in (".", "..")
            and re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None
        )

    def _serve_manifest(self, path):
        try:
            control = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._error(404, "manifest not found")
            return
        except (OSError, json.JSONDecodeError):
            self._error(500, "invalid repository manifest")
            return
        if not isinstance(control, dict) or control.get("control_format") != 1:
            self._error(500, "unsigned repository manifest; republish required")
            return
        selected = control.get("current")
        rollout = control.get("rollout_percentage", 100)
        installation = self.headers.get("X-PVM-Installation-ID", "")
        bucket = None
        if (
            isinstance(rollout, int)
            and rollout < 100
            and isinstance(control.get("previous"), dict)
        ):
            if installation:
                bucket = int.from_bytes(
                    hashlib.sha256(installation.encode("utf-8")).digest()[:8], "big"
                ) % 100
            if bucket is None or bucket >= rollout:
                selected = control["previous"]
        try:
            payload = decode_envelope(selected)[0]
        except CompileError:
            self._error(500, "invalid signed repository manifest")
            return
        body = (json.dumps(selected, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        self.server.audit(
            "manifest",
            {
                "bucket": bucket,
                "path": str(path.relative_to(self.server.repository)),
                "release": payload.get("release"),
                "request_id": self.request_id,
                "rollout": rollout,
            },
        )
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        if self.headers.get("If-None-Match") == etag:
            self._send(304, headers={"ETag": etag})
            return
        self._send(
            200,
            body,
            headers={"Cache-Control": "private, max-age=60", "ETag": etag},
        )

    def _serve_module(self, filename):
        if len(filename) != 68 or not filename.endswith(".pvm"):
            self._error(404, "invalid module hash")
            return
        digest = filename[:-4]
        if any(ch not in "0123456789abcdef" for ch in digest):
            self._error(404, "invalid module hash")
            return
        protected = self.server.module_requires_activation(digest)
        if protected and not self._authorized():
            self.server.audit(
                "authorization_denied",
                {"request_id": self.request_id, "sha256": digest},
            )
            self._error(401, "activation required")
            return
        path = self.server.repository / "modules" / filename
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            self._error(404, "module not found")
            return
        if hashlib.sha256(body).hexdigest() != digest:
            self._error(500, "repository integrity failure")
            return
        self.server.audit(
            "module",
            {"request_id": self.request_id, "sha256": digest, "size": len(body)},
        )
        self._send(
            200,
            body,
            content_type="application/vnd.pvm.module",
            headers={
                "Cache-Control": (
                    "private, max-age=31536000, immutable"
                    if protected
                    else "public, max-age=31536000, immutable"
                ),
                "Vary": "Authorization",
            },
        )

    def log_message(self, message, *args):
        print("%s - %s" % (self.address_string(), message % args))


class ModuleServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(
        self,
        address,
        repository,
        activation_token,
        allow_unauthenticated=False,
        audit_path=None,
        request_timeout=15,
    ):
        super().__init__(address, ModuleHandler)
        self.repository = Path(repository).resolve()
        if not self.repository.is_dir():
            self.server_close()
            raise ValueError("module repository does not exist: %s" % self.repository)
        self.activation_token = activation_token
        self.allow_unauthenticated = allow_unauthenticated
        self.audit_path = Path(audit_path) if audit_path else None
        self.audit_lock = threading.Lock()
        self.request_timeout = request_timeout

    def audit(self, event, fields):
        if self.audit_path is None:
            return
        record = {"event": event, "timestamp": int(time.time()), **fields}
        encoded = json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
        with self.audit_lock:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as output:
                output.write(encoded)

    def module_requires_activation(self, digest):
        access = self.repository / "access" / (digest + ".json")
        try:
            policy = json.loads(access.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return policy.get("authorization") == "activation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--activation-token-file", type=Path)
    parser.add_argument("--request-timeout", default=15, type=int)
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    parser.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="development only: allow provisioned manifests without an activation token",
    )
    args = parser.parse_args()
    if args.request_timeout < 1 or args.request_timeout > 300:
        parser.error("--request-timeout must be between 1 and 300 seconds")
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert and --tls-key must be supplied together")
    token_file = args.activation_token_file or (
        Path(os.environ["PVM_ACTIVATION_TOKEN_FILE"])
        if os.environ.get("PVM_ACTIVATION_TOKEN_FILE")
        else None
    )
    token = (
        token_file.read_text(encoding="utf-8").strip()
        if token_file
        else os.environ.get("PVM_ACTIVATION_TOKEN", "")
    )
    server = ModuleServer(
        (args.host, args.port),
        args.repository,
        token,
        args.allow_unauthenticated,
        args.audit_log,
        args.request_timeout,
    )
    scheme = "http"
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"
    print("module service listening on %s://%s:%d" % (scheme, args.host, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
