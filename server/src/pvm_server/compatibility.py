#!/usr/bin/env python3
"""Build and validate the five-domain x historical-bytecode compatibility matrix."""

import argparse
import json
import subprocess
from pathlib import Path

from .compiler import CompileError, compile_file


def variants(base, domains):
    for domain, settings in sorted(domains.items()):
        for bytecode in (1, 2, 3):
            source = json.loads(json.dumps(base))
            source["module"]["id"] = "%s.home" % domain
            source["module"]["application_id"] = "com.example.pvm.%s" % domain
            source["module"]["capabilities"] = settings["capabilities"]
            source["module"]["network_domains"] = settings["networkDomains"]
            source["module"]["minimum_runtime"] = bytecode
            source["module"]["release"] = bytecode
            source["handlers"].pop("set_name", None)
            source["pages"]["main"]["children"] = [
                node
                for node in source["pages"]["main"]["children"]
                if node["id"] != "counter_name"
            ]
            surface = settings.get("surface")
            if surface:
                source["pages"]["main"]["children"].append(
                    {
                        "type": "native_surface",
                        "id": "%s_surface" % domain,
                        "props": {"surface_type": surface},
                    }
                )
            if bytecode == 1:
                source["handlers"].pop("load_status")
                source["pages"]["main"]["children"] = [
                    node
                    for node in source["pages"]["main"]["children"]
                    if node["id"] != "counter_load_status"
                ]
            yield domain, bytecode, source


def verify(base_path, matrix_path, private_key, public_key, runtime, output):
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    domains = json.loads(Path(matrix_path).read_text(encoding="utf-8"))
    results = []
    for domain, bytecode, source in variants(base, domains):
        source_path = Path(output) / domain / ("v%d.json" % bytecode)
        module_path = source_path.with_suffix(".pvm")
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = compile_file(source_path, private_key, module_path, format_version=bytecode)
        completed = subprocess.run(
            [
                str(runtime),
                "--module",
                str(module_path),
                "--public-key",
                str(public_key),
                "--app-id",
                source["module"]["application_id"],
                "--validate-only",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode:
            raise CompileError("%s v%d failed: %s" % (domain, bytecode, completed.stderr.strip()))
        results.append({"domain": domain, "bytecode": bytecode, **result})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="server/sample/counter.pvm.json", type=Path)
    parser.add_argument("--matrix", default="server/sample/domain-matrix.json", type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", default="build/compatibility", type=Path)
    args = parser.parse_args()
    try:
        result = verify(
            args.base,
            args.matrix,
            args.private_key,
            args.public_key,
            args.runtime,
            args.output,
        )
    except (OSError, json.JSONDecodeError, CompileError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
