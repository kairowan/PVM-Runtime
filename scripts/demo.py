#!/usr/bin/env python3
"""Run the local compiler -> service -> provisioner -> C++ VM demonstration."""

import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from pvm_server.publish import publish  # noqa: E402
from pvm_server.serve import ModuleServer  # noqa: E402


def main():
    private_key = ROOT / "server" / "var" / "keys" / "dev-private.pem"
    public_key = ROOT / "server" / "var" / "keys" / "dev-public.pem"
    runtime = ROOT / "build" / "client" / "pvm_cli"
    if not private_key.is_file() or not public_key.is_file() or not runtime.is_file():
        raise SystemExit("run `make bootstrap build` first")
    repository = ROOT / "server" / "var" / "repository"
    publish(ROOT / "server" / "sample" / "counter.pvm.json", private_key, repository)

    server = ModuleServer(("127.0.0.1", 0), repository, "local-demo-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provision = subprocess.run(
            [
                sys.executable,
                str(ROOT / "client" / "tools" / "provision.py"),
                "--server",
                "http://127.0.0.1:%d" % server.server_address[1],
                "--app-id",
                "com.example.protected",
                "--channel",
                "enterprise",
                "--profile",
                "online_provisioned",
                "--platform",
                "desktop",
                "--token",
                "local-demo-token",
                "--cache",
                str(ROOT / "client" / "var" / "cache"),
                "--runtime",
                str(runtime),
                "--public-key",
                str(public_key),
            ],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        module = provision.stdout.strip()
        subprocess.run(
            [
                str(runtime),
                "--module",
                module,
                "--public-key",
                str(public_key),
                "--app-id",
                "com.example.protected",
                "--state-file",
                str(ROOT / "client" / "var" / "counter.state"),
                "--tap-index",
                "0",
            ],
            check=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
