#!/usr/bin/env python3
"""Fail release artifacts that expose forbidden plaintext or unexpected symbols."""

import argparse
import re
import subprocess
from pathlib import Path

from .compiler import CompileError


def scan_strings(path, forbidden):
    body = Path(path).read_bytes()
    leaked = [value for value in forbidden if value.encode("utf-8") in body]
    if leaked:
        raise CompileError("forbidden plaintext in %s: %s" % (path, ", ".join(leaked)))


def scan_exports(path, nm, allowed):
    completed = subprocess.run(
        [nm, "-g", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if completed.returncode:
        raise CompileError("symbol scan failed: " + completed.stderr.strip())
    pattern = re.compile(allowed)
    unexpected = []
    for line in completed.stdout.splitlines():
        symbol = line.split()[-1] if line.split() else ""
        if symbol and not symbol.startswith("_") and not pattern.fullmatch(symbol):
            unexpected.append(symbol)
    if unexpected:
        raise CompileError("unexpected exported symbols: " + ", ".join(sorted(set(unexpected))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--forbid", action="append", default=[])
    parser.add_argument("--forbid-file", type=Path)
    parser.add_argument("--nm")
    parser.add_argument("--allowed-symbol", default=r"(pvm_|Java_|JNI_|napi_).*")
    args = parser.parse_args()
    forbidden = list(args.forbid)
    if args.forbid_file:
        forbidden += [
            line.strip()
            for line in args.forbid_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    try:
        scan_strings(args.artifact, forbidden)
        if args.nm:
            scan_exports(args.artifact, args.nm, args.allowed_symbol)
    except (OSError, CompileError) as error:
        parser.error(str(error))
    print(args.artifact)


if __name__ == "__main__":
    main()
