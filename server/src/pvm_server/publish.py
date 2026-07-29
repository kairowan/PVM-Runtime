#!/usr/bin/env python3
"""Compile and atomically publish an immutable PVM module plus its manifest."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .compiler import CompileError, compile_file
from .host_idl import DEFAULT_IDL, load as load_host_idl
from .manifest import create_envelope, decode_envelope, legacy_payload
from .tooling import lint


def _write_json_atomic(path, value):
    encoded = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(str(temporary), str(path))


def _load_current_control(path, private_key, signer_command):
    control = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(control, dict) and control.get("control_format") == 1:
        envelope = control.get("current")
        payload = decode_envelope(envelope)[0]
        return control, envelope, payload
    if not isinstance(control, dict):
        raise CompileError("invalid published manifest")
    payload = legacy_payload(control)
    envelope = create_envelope(payload, private_key, signer_command)
    migrated = {
        "control_format": 1,
        "current": envelope,
        "rollout_percentage": int(control.get("rollout_percentage", 100)),
    }
    previous = control.get("previous")
    if isinstance(previous, dict):
        migrated["previous"] = create_envelope(
            legacy_payload(previous), private_key, signer_command
        )
    return migrated, envelope, payload


def publish(source, private_key, repository, signer_command=None, host_idl=DEFAULT_IDL):
    try:
        source_body = json.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompileError("cannot read DSL source: %s" % error)
    lint(source_body, load_host_idl(host_idl))
    repository = Path(repository)
    modules = repository / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pvm-publish-") as directory:
        compiled = Path(directory) / "module.pvm"
        result = compile_file(source, private_key, compiled, signer_command=signer_command)
        destination = modules / (result["sha256"] + ".pvm")
        if not destination.exists():
            temporary_module = destination.with_suffix(".pvm.tmp")
            shutil.copyfile(str(compiled), str(temporary_module))
            os.replace(str(temporary_module), str(destination))
    access = repository / "access" / (result["sha256"] + ".json")
    access.parent.mkdir(parents=True, exist_ok=True)
    access_value = {
        "authorization": (
            "activation"
            if result["profile"] in ("online_provisioned", "enterprise_managed")
            else "public"
        ),
        "sha256": result["sha256"],
    }
    _write_json_atomic(access, access_value)

    manifest_dir = (
        repository
        / "apps"
        / result["application_id"]
        / result["channel"]
        / result["platform"]
        / result["profile"]
    )
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    if manifest_path.exists():
        control, previous_envelope, previous_payload = _load_current_control(
            manifest_path, private_key, signer_command
        )
        if (
            int(previous_payload["release"]) == result["release"]
            and previous_payload["sha256"] == result["sha256"]
        ):
            _write_json_atomic(manifest_path, control)
            return previous_payload
        if int(previous_payload["release"]) >= result["release"]:
            raise CompileError(
                "anti-rollback: release %d is not newer than published release %s"
                % (result["release"], previous_payload["release"])
            )
        history = manifest_dir / "history"
        history.mkdir(parents=True, exist_ok=True)
        previous_path = history / (
            "%s-%s.json" % (previous_payload["release"], previous_payload["sha256"])
        )
        if not previous_path.exists():
            _write_json_atomic(previous_path, previous_envelope)
    else:
        previous_envelope = None
    payload = {
        "application_id": result["application_id"],
        "bytecode_format": result["bytecode_format"],
        "capability_versions": result["capability_versions"],
        "channel": result["channel"],
        "format": 2,
        "minimum_runtime": result["minimum_runtime"],
        "module_url": "/v1/modules/%s.pvm" % result["sha256"],
        "profile": result["profile"],
        "platform": result["platform"],
        "release": result["release"],
        "sha256": result["sha256"],
        "size": result["size"],
    }
    control = {
        "control_format": 1,
        "current": create_envelope(payload, private_key, signer_command),
        "rollout_percentage": 100,
    }
    if previous_envelope is not None:
        control["previous"] = previous_envelope
    _write_json_atomic(manifest_path, control)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    signing = parser.add_mutually_exclusive_group(required=True)
    signing.add_argument("--private-key", type=Path)
    signing.add_argument("--signer-command")
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--host-idl", default=DEFAULT_IDL, type=Path)
    args = parser.parse_args()
    try:
        manifest = publish(
            args.source,
            args.private_key,
            args.repository,
            args.signer_command,
            args.host_idl,
        )
    except CompileError as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
