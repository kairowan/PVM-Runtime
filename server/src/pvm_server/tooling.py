#!/usr/bin/env python3
"""Format or lint DSL sources against the compiler and versioned host IDL."""

import argparse
import json
import os
from pathlib import Path

from .compiler import CompileError, Compiler
from .host_idl import load as load_host_idl


def lint(source, host_idl):
    Compiler(source).build()
    capabilities = {item["id"]: item for item in host_idl["capabilities"]}
    components = {item["id"]: item for item in host_idl["components"]}
    declared = set(source["module"].get("capabilities", []))
    unknown = declared - set(capabilities)
    if unknown:
        raise CompileError("unknown host capabilities: " + ", ".join(sorted(unknown)))
    required_versions = source["module"].get("capability_versions", {})
    incompatible = [
        "%s requires %d but IDL provides %d"
        % (capability, required_versions.get(capability, 1), capabilities[capability]["version"])
        for capability in sorted(declared)
        if required_versions.get(capability, 1) > capabilities[capability]["version"]
    ]
    if incompatible:
        raise CompileError("incompatible host capability versions: " + ", ".join(incompatible))
    for handler_name, instructions in source.get("handlers", {}).items():
        for instruction in instructions:
            if instruction.get("op") not in ("effect", "effect.async"):
                continue
            capability = capabilities[instruction["capability"]]
            operation_name = instruction.get("operation")
            operation = capability["operations"].get(operation_name)
            if operation is None:
                raise CompileError(
                    "unknown operation %s.%s in %s"
                    % (capability["id"], operation_name, handler_name)
                )
            expected_op = "effect.async" if capability["async"] else "effect"
            if instruction["op"] != expected_op:
                raise CompileError("%s must use %s" % (capability["id"], expected_op))
            if instruction.get("args", 0) != len(operation["args"]):
                raise CompileError(
                    "%s.%s expects %d arguments"
                    % (capability["id"], operation_name, len(operation["args"]))
                )
    for page in source.get("pages", {}).values():
        for node in _nodes(page):
            if node.get("type") == "native_surface":
                component = node.get("props", {}).get("surface_type")
                if component not in components:
                    raise CompileError("unknown NativeSurface component: %r" % component)
    return True


def _nodes(root):
    yield root
    for child in root.get("children", []):
        yield from _nodes(child)


def format_file(path, check=False):
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    encoded = json.dumps(source, indent=2, sort_keys=True) + "\n"
    if check:
        if Path(path).read_text(encoding="utf-8") != encoded:
            raise CompileError("DSL source is not canonically formatted: %s" % path)
        return
    temporary = Path(path).with_suffix(Path(path).suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(str(temporary), str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("format", "lint"))
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--idl", default="spec/host_idl.json", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        host_idl = load_host_idl(args.idl)
        for path in args.sources:
            if args.action == "format":
                format_file(path, args.check)
            else:
                lint(json.loads(path.read_text(encoding="utf-8")), host_idl)
    except (OSError, json.JSONDecodeError, CompileError) as error:
        parser.error(str(error))
    print("\n".join(str(path) for path in args.sources))


if __name__ == "__main__":
    main()
