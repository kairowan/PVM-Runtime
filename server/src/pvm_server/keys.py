#!/usr/bin/env python3
"""Create a local Ed25519 development keypair without overwriting existing keys."""

import argparse
import os
import subprocess
from pathlib import Path

from .compiler import CompileError, find_openssl


def run(command):
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode:
        raise CompileError(completed.stderr.strip() or "OpenSSL key operation failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    openssl = find_openssl()
    if openssl is None:
        parser.error("OpenSSL 3 executable was not found; set PVM_OPENSSL")
    args.directory.mkdir(parents=True, exist_ok=True)
    private_key = args.directory / "dev-private.pem"
    public_key = args.directory / "dev-public.pem"
    if private_key.exists() != public_key.exists():
        parser.error("incomplete keypair exists; move it aside before regenerating")
    if not private_key.exists():
        try:
            run([openssl, "genpkey", "-algorithm", "ED25519", "-out", str(private_key)])
            run(
                [
                    openssl,
                    "pkey",
                    "-in",
                    str(private_key),
                    "-pubout",
                    "-out",
                    str(public_key),
                ]
            )
        except CompileError as error:
            private_key.unlink(missing_ok=True)
            public_key.unlink(missing_ok=True)
            parser.error(str(error))
        os.chmod(str(private_key), 0o600)
    print(public_key)


if __name__ == "__main__":
    main()
