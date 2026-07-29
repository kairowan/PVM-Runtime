#!/usr/bin/env python3
"""Check that the compiler and renderer contract describe the same UI semantics."""

import argparse
import json
from pathlib import Path

from .compiler import CompileError, EVENT_TYPES, NODE_TYPES, PROPERTY_KEYS


def check(path):
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompileError("cannot read renderer conformance spec: %s" % error)
    expected_nodes = sorted(name.title().replace("_", "") for name in NODE_TYPES)
    expected_properties = sorted(
        "".join([parts[0], *[part.title() for part in parts[1:]]])
        for parts in (name.split("_") for name in PROPERTY_KEYS)
    )
    if spec.get("schemaVersion") != 1:
        raise CompileError("unsupported renderer conformance schema")
    if spec.get("nodeTypes") != expected_nodes:
        raise CompileError("renderer node types drifted from the compiler")
    if spec.get("properties") != expected_properties:
        raise CompileError("renderer properties drifted from the compiler")
    if spec.get("events") != sorted(EVENT_TYPES):
        raise CompileError("renderer events drifted from the compiler")
    required = {
        "android-view",
        "android-compose-cmp",
        "uikit",
        "swiftui",
        "arkui",
        "kuikly",
    }
    if set(spec.get("backends", {})) != required:
        raise CompileError("renderer backend matrix is incomplete")
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default="spec/renderer_conformance.json", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.spec)
    except CompileError as error:
        parser.error(str(error))
    print(json.dumps(result["backends"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
