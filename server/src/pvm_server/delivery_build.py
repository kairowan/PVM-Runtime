#!/usr/bin/env python3
"""Build client/server artifacts for one or all supported delivery profiles."""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from .compiler import CompileError, PROFILES, compile_file
from .host_manifest import generate as generate_host_manifest
from .host_idl import DEFAULT_IDL, load as load_host_idl
from .manifest import create_envelope
from .tooling import lint


PLATFORMS = ("android", "ios", "harmonyos")
PACKAGE_FORMATS = {
    "android": ["apk", "aab"],
    "ios": ["ipa"],
    "harmonyos": ["hap"],
}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(str(temporary), str(path))


def _delivery(profile, platform):
    return {
        "profile": profile,
        "platform": platform,
        "fallback_ui": profile == "online_provisioned",
        "startup_dependencies_bundled": profile == "offline_sealed",
        "native_dynamic_download": False,
        "external_code_artifacts": [],
    }


def build(source, private_key, public_key, output, host_idl=DEFAULT_IDL):
    lint(source, load_host_idl(host_idl))
    output = Path(output)
    profile = source["delivery"]["profile"]
    platform = source["delivery"]["platform"]
    client = output / "client" / platform / profile
    server = output / "server" / platform / profile
    client.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pvm-delivery-") as directory:
        source_path = Path(directory) / "source.json"
        module_path = Path(directory) / "module.pvm"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        result = compile_file(source_path, private_key, module_path)
        immutable_name = result["sha256"] + ".pvm"
        if profile in ("offline_sealed", "store_on_demand"):
            shutil.copyfile(module_path, client / "module.pvm")
        else:
            modules = server / "repository" / "modules"
            modules.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(module_path, modules / immutable_name)
            _write_json(
                server / "repository" / "access" / (result["sha256"] + ".json"),
                {
                    "authorization": "activation",
                    "sha256": result["sha256"],
                },
            )

    shutil.copyfile(public_key, client / "module-public-key.pem")
    _write_json(client / "host-capabilities.json", generate_host_manifest(source))
    bootstrap = {
        "applicationId": result["application_id"],
        "builtInFallbackRequired": profile != "offline_sealed",
        "channel": result["channel"],
        "capabilityVersions": result["capability_versions"],
        "mode": {
            "offline_sealed": "bundled",
            "online_provisioned": "remote",
            "store_on_demand": "store-resource",
            "enterprise_managed": "managed-remote",
        }[profile],
        "packageFormats": PACKAGE_FORMATS[platform],
        "platform": platform,
        "profile": profile,
        "publicKey": "module-public-key.pem",
        "release": result["release"],
        "sha256": result["sha256"],
    }
    _write_json(client / "bootstrap.json", bootstrap)
    if profile in ("online_provisioned", "enterprise_managed"):
        payload = {
            "application_id": result["application_id"],
            "bytecode_format": result["bytecode_format"],
            "capability_versions": result["capability_versions"],
            "channel": result["channel"],
            "format": 2,
            "minimum_runtime": result["minimum_runtime"],
            "module_url": "/v1/modules/%s" % immutable_name,
            "profile": result["profile"],
            "platform": result["platform"],
            "release": result["release"],
            "sha256": result["sha256"],
            "size": result["size"],
        }
        manifest = {
            "control_format": 1,
            "current": create_envelope(payload, private_key),
            "rollout_percentage": 100,
        }
        manifest_path = (
            server
            / "repository"
            / "apps"
            / result["application_id"]
            / result["channel"]
            / platform
            / profile
            / "manifest.json"
        )
        _write_json(manifest_path, manifest)
    if profile == "enterprise_managed":
        _write_json(
            server / "enterprise-policy.json",
            {
                "activationRequired": True,
                "allowManagedRollback": True,
                "deviceAttestation": "host-policy",
                "organizationCertificate": "deployment-required",
            },
        )
    return bootstrap


def build_matrix(source, private_key, public_key, output, host_idl=DEFAULT_IDL):
    results = []
    for platform in PLATFORMS:
        for profile in PROFILES:
            variant = json.loads(json.dumps(source))
            variant["delivery"] = _delivery(profile, platform)
            results.append(build(variant, private_key, public_key, output, host_idl))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--host-idl", default=DEFAULT_IDL, type=Path)
    parser.add_argument("--all", action="store_true", help="build 3 platforms x 4 profiles")
    args = parser.parse_args()
    try:
        source = json.loads(args.source.read_text(encoding="utf-8"))
        results = (
            build_matrix(
                source, args.private_key, args.public_key, args.output, args.host_idl
            )
            if args.all
            else [
                build(
                    source,
                    args.private_key,
                    args.public_key,
                    args.output,
                    args.host_idl,
                )
            ]
        )
    except (OSError, json.JSONDecodeError, CompileError) as error:
        parser.error(str(error))
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
