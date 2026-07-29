#!/usr/bin/env python3
"""Small production-shaped reference module service using immutable module URLs."""

import argparse
import hashlib
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .compiler import CompileError
from .manifest import decode_envelope


class ModuleHandler(BaseHTTPRequestHandler):
    server_version = "PVMModuleService/0.1"

    def _send(self, status, body=b"", content_type="application/json", headers=None):
        headers = headers or {}
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
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

    def do_GET(self):
        raw_path = unquote(urlparse(self.path).path)
        parts = [part for part in raw_path.split("/") if part]
        if parts == ["healthz"]:
            self._send(200, b'{"status":"ok"}\n')
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
            self.server.audit("authorization_denied", {"sha256": digest})
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
        self.server.audit("module", {"sha256": digest, "size": len(body)})
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
    def __init__(
        self, address, repository, activation_token, allow_unauthenticated=False, audit_path=None
    ):
        super().__init__(address, ModuleHandler)
        self.repository = Path(repository).resolve()
        self.activation_token = activation_token
        self.allow_unauthenticated = allow_unauthenticated
        self.audit_path = Path(audit_path) if audit_path else None
        self.audit_lock = threading.Lock()

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
    parser.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="development only: allow provisioned manifests without an activation token",
    )
    args = parser.parse_args()
    token = os.environ.get("PVM_ACTIVATION_TOKEN", "")
    server = ModuleServer(
        (args.host, args.port),
        args.repository,
        token,
        args.allow_unauthenticated,
        args.audit_log,
    )
    print("module service listening on http://%s:%d" % (args.host, args.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
