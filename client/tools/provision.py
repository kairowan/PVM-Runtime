#!/usr/bin/env python3
"""Provision a signed module with last-known-good and atomic cache switching."""

import argparse
import base64
import binascii
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def request(url, token="", etag="", installation_id=""):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if etag:
        headers["If-None-Match"] = etag
    if installation_id:
        headers["X-PVM-Installation-ID"] = installation_id
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(str(temporary), str(path))
    os.chmod(path, 0o600)


def verify_manifest_envelope(encoded, args):
    try:
        envelope = json.loads(encoded.decode("utf-8"))
        if (
            not isinstance(envelope, dict)
            or envelope.get("envelope_format") != 1
            or envelope.get("signature_algorithm") != "Ed25519"
        ):
            raise RuntimeError("invalid signed manifest envelope")
        payload_bytes = base64.b64decode(envelope["payload"], validate=True)
        signature = base64.b64decode(envelope["signature"], validate=True)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise RuntimeError("invalid signed manifest encoding: %s" % error)
    canonical = (
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    if not isinstance(payload, dict) or canonical != payload_bytes or len(signature) != 64:
        raise RuntimeError("invalid signed manifest payload")
    with tempfile.TemporaryDirectory(prefix="pvm-manifest-") as directory:
        payload_path = Path(directory) / "payload.json"
        signature_path = Path(directory) / "signature.bin"
        payload_path.write_bytes(payload_bytes)
        signature_path.write_bytes(signature)
        completed = subprocess.run(
            [
                str(args.runtime),
                "--verify-payload",
                str(payload_path),
                "--verify-signature",
                str(signature_path),
                "--public-key",
                str(args.public_key),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    if completed.returncode:
        raise RuntimeError(
            "manifest signature verification failed: " + completed.stderr.strip()
        )
    return payload


def provision_strict(args):
    cache = args.cache.resolve()
    modules = cache / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    state_path = cache / "current.json"
    state = read_json(state_path, {})
    installed_release = int(state.get("release", 0))
    manifest_url = "%s/v1/apps/%s/%s/%s/%s/manifest" % (
        args.server.rstrip("/"),
        args.app_id,
        args.channel,
        args.platform,
        args.profile,
    )
    cached_module = modules / (state.get("sha256", "") + ".pvm")
    usable_cache = cached_module.is_file() and installed_release >= args.minimum_release
    if cached_module.is_file():
        os.chmod(cached_module, 0o600)
    try:
        with request(
            manifest_url,
            args.token,
            state.get("etag", "") if usable_cache else "",
            args.installation_id,
        ) as response:
            encoded_manifest = response.read()
            etag = response.headers.get("ETag", "")
    except urllib.error.HTTPError as error:
        if error.code == 304 and usable_cache:
            print(str(cached_module))
            return
        if usable_cache:
            print("manifest unavailable; using last-known-good module", file=sys.stderr)
            print(str(cached_module))
            return
        raise
    except urllib.error.URLError:
        if usable_cache:
            print("network unavailable; using last-known-good module", file=sys.stderr)
            print(str(cached_module))
            return
        raise
    manifest = verify_manifest_envelope(encoded_manifest, args)

    required = {
        "application_id",
        "channel",
        "minimum_runtime",
        "module_url",
        "profile",
        "platform",
        "release",
        "sha256",
        "size",
    }
    if not required.issubset(manifest):
        raise RuntimeError("manifest is missing required fields")
    if (
        manifest["application_id"] != args.app_id
        or manifest["channel"] != args.channel
        or manifest["profile"] != args.profile
        or manifest["platform"] != args.platform
    ):
        raise RuntimeError("manifest binding mismatch")
    minimum_release = max(installed_release, args.minimum_release)
    if int(manifest["release"]) < minimum_release:
        raise RuntimeError("manifest rejected by anti-rollback policy")
    digest = manifest["sha256"]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("manifest contains an invalid module hash")
    if manifest["module_url"] != "/v1/modules/%s.pvm" % digest:
        raise RuntimeError("manifest module URL is not bound to its content hash")
    destination = modules / (digest + ".pvm")

    if destination.exists():
        body = destination.read_bytes()
        if len(body) != int(manifest["size"]) or hashlib.sha256(body).hexdigest() != digest:
            destination.unlink()
    if not destination.exists():
        module_url = args.server.rstrip("/") + manifest["module_url"]
        with request(module_url, args.token) as response:
            body = response.read(int(manifest["size"]) + 1)
        if len(body) != int(manifest["size"]) or hashlib.sha256(body).hexdigest() != digest:
            raise RuntimeError("downloaded module failed size/hash verification")
        temporary = modules / (digest + ".tmp")
        try:
            with temporary.open("wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            validate = [
                str(args.runtime),
                "--module",
                str(temporary),
                "--public-key",
                str(args.public_key),
                "--app-id",
                args.app_id,
                "--min-release",
                str(minimum_release),
                "--validate-only",
            ]
            completed = subprocess.run(
                validate, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if completed.returncode:
                raise RuntimeError("VM preload validation failed: " + completed.stderr.strip())
            os.replace(str(temporary), str(destination))
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    history = [digest] + [
        item for item in state.get("history", []) if item != digest and (modules / (item + ".pvm")).exists()
    ]
    history = history[:2]
    new_state = {
        "etag": etag,
        "history": history,
        "release": int(manifest["release"]),
        "sha256": digest,
    }
    atomic_json(state_path, new_state)
    for candidate in modules.glob("*.pvm"):
        if candidate.stem not in history:
            candidate.unlink()
    print(str(destination))


def provision(args):
    try:
        return provision_strict(args)
    except Exception as error:
        state = read_json(args.cache.resolve() / "current.json", {})
        cached = args.cache.resolve() / "modules" / (state.get("sha256", "") + ".pvm")
        if cached.is_file() and int(state.get("release", 0)) >= args.minimum_release:
            print(
                "module refresh failed (%s); using last-known-good module" % error,
                file=sys.stderr,
            )
            print(str(cached))
            return
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument(
        "--platform", choices=("android", "ios", "harmonyos", "desktop"), default="desktop"
    )
    parser.add_argument("--token", default=os.environ.get("PVM_ACTIVATION_TOKEN", ""))
    parser.add_argument("--installation-id", default="")
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument(
        "--minimum-release",
        default=0,
        type=int,
        help="immutable install-time release floor for first-install anti-rollback",
    )
    args = parser.parse_args()
    if args.minimum_release < 0:
        parser.error("--minimum-release must be non-negative")
    provision(args)


if __name__ == "__main__":
    main()
