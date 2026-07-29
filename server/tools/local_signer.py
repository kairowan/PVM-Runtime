#!/usr/bin/env python3
"""Development adapter for the signer-command stdin/stdout protocol."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openssl", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args()
    payload = sys.stdin.buffer.read()
    with tempfile.TemporaryDirectory(prefix="pvm-local-signer-") as directory:
        source = Path(directory) / "payload.bin"
        signature = Path(directory) / "signature.bin"
        source.write_bytes(payload)
        completed = subprocess.run(
            [
                args.openssl,
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(args.private_key),
                "-in",
                str(source),
                "-out",
                str(signature),
            ],
            stderr=subprocess.PIPE,
        )
        if completed.returncode:
            sys.stderr.buffer.write(completed.stderr)
            raise SystemExit(completed.returncode)
        sys.stdout.buffer.write(signature.read_bytes())


if __name__ == "__main__":
    main()
