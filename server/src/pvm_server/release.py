#!/usr/bin/env python3
"""Set rollout or stop it safely; upgraded clients retain anti-rollback protection."""

import argparse
import json
import os
from pathlib import Path

from .compiler import CompileError


def _write(path, value):
    encoded = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(str(temporary), str(path))


def set_rollout(path, percentage):
    if not 0 <= percentage <= 100:
        raise CompileError("rollout percentage must be in [0, 100]")
    path = Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("control_format") != 1:
        raise CompileError("unsigned manifest control; republish required")
    if percentage < 100 and not isinstance(manifest.get("previous"), dict):
        raise CompileError("a partial rollout requires a previous release")
    manifest["rollout_percentage"] = percentage
    _write(path, manifest)
    return manifest


def rollback(path):
    path = Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("control_format") != 1:
        raise CompileError("unsigned manifest control; republish required")
    if not isinstance(manifest.get("previous"), dict):
        raise CompileError("manifest has no previous release")
    manifest["rollout_percentage"] = 0
    _write(path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--percentage", type=int)
    action.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    try:
        result = rollback(args.manifest) if args.rollback else set_rollout(
            args.manifest, args.percentage
        )
    except (OSError, json.JSONDecodeError, CompileError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
