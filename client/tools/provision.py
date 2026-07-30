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

MAX_MANIFEST_BYTES = 64 * 1024
MAX_MODULE_BYTES = 16 * 1024 * 1024


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def request(url, token="", etag="", installation_id=""):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    if etag:
        headers["If-None-Match"] = etag
    if installation_id:
        headers["X-PVM-Installation-ID"] = installation_id
    return OPENER.open(urllib.request.Request(url, headers=headers), timeout=15)


def is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def read_bound_state(path, args):
    try:
        if not 1 <= path.stat().st_size <= 16 * 1024:
            return {}
    except FileNotFoundError:
        return {}
    state = read_json(path, {})
    history = state.get("history")
    if (
        state.get("format") != 1
        or state.get("application_id") != args.app_id
        or state.get("channel") != args.channel
        or state.get("platform") != args.platform
        or state.get("profile") != args.profile
        or not isinstance(state.get("etag"), str)
        or type(state.get("release")) is not int
        or state["release"] < 1
        or not is_sha256(state.get("sha256"))
        or not isinstance(history, list)
        or not 1 <= len(history) <= 2
        or history[0] != state["sha256"]
        or len(set(history)) != len(history)
        or not all(is_sha256(value) for value in history)
    ):
        return {}
    return state


def cached_module(state, args):
    if not state or state["release"] < args.minimum_release:
        return None
    path = args.cache.resolve() / "modules" / (state["sha256"] + ".pvm")
    if not path.is_file() or not 1 <= path.stat().st_size <= MAX_MODULE_BYTES:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(16 * 1024), b""):
            digest.update(chunk)
    return path if digest.hexdigest() == state["sha256"] else None


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


def validate_module(path, minimum_release, args):
    completed = subprocess.run(
        [
            str(args.runtime),
            "--module",
            str(path),
            "--public-key",
            str(args.public_key),
            "--app-id",
            args.app_id,
            "--min-release",
            str(minimum_release),
            "--channel",
            args.channel,
            "--platform",
            args.platform,
            "--profile",
            args.profile,
            "--validate-only",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError("VM preload validation failed: " + completed.stderr.strip())


def provision_strict(args):
    cache = args.cache.resolve()
    modules = cache / "modules"
    modules.mkdir(parents=True, exist_ok=True)
    state_path = cache / "current.json"
    state = read_bound_state(state_path, args)
    installed_release = int(state.get("release", 0))
    manifest_url = "%s/v1/apps/%s/%s/%s/%s/manifest" % (
        args.server.rstrip("/"),
        args.app_id,
        args.channel,
        args.platform,
        args.profile,
    )
    cached = cached_module(state, args)
    usable_cache = cached is not None
    if cached is not None:
        os.chmod(cached, 0o600)
    try:
        with request(
            manifest_url,
            args.token,
            state.get("etag", "") if usable_cache else "",
            args.installation_id,
        ) as response:
            encoded_manifest = response.read(MAX_MANIFEST_BYTES + 1)
            etag = response.headers.get("ETag", "")
            if len(encoded_manifest) > MAX_MANIFEST_BYTES:
                raise RuntimeError("manifest exceeds its size budget")
    except urllib.error.HTTPError as error:
        if error.code == 304 and usable_cache:
            print(str(cached))
            return
        if usable_cache:
            print("manifest unavailable; using last-known-good module", file=sys.stderr)
            print(str(cached))
            return
        raise
    except urllib.error.URLError:
        if usable_cache:
            print("network unavailable; using last-known-good module", file=sys.stderr)
            print(str(cached))
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
    if type(manifest["release"]) is not int or not 1 <= manifest["release"] <= 2**64 - 1:
        raise RuntimeError("manifest release is invalid")
    minimum_release = max(installed_release, args.minimum_release)
    if manifest["release"] < minimum_release:
        raise RuntimeError("manifest rejected by anti-rollback policy")
    digest = manifest["sha256"]
    if not is_sha256(digest):
        raise RuntimeError("manifest contains an invalid module hash")
    if type(manifest["size"]) is not int or not 1 <= manifest["size"] <= MAX_MODULE_BYTES:
        raise RuntimeError("manifest module size is invalid")
    if manifest["module_url"] != "/v1/modules/%s.pvm" % digest:
        raise RuntimeError("manifest module URL is not bound to its content hash")
    destination = modules / (digest + ".pvm")

    if destination.exists():
        if not destination.is_file() or destination.stat().st_size != manifest["size"]:
            destination.unlink()
        elif hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            destination.unlink()
    if not destination.exists():
        module_url = args.server.rstrip("/") + manifest["module_url"]
        with request(module_url, args.token) as response:
            body = response.read(manifest["size"] + 1)
        if len(body) != manifest["size"] or hashlib.sha256(body).hexdigest() != digest:
            raise RuntimeError("downloaded module failed size/hash verification")
        temporary = modules / (digest + ".tmp")
        try:
            with temporary.open("wb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            validate_module(temporary, minimum_release, args)
            os.replace(str(temporary), str(destination))
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        validate_module(destination, minimum_release, args)

    history = [digest] + [
        item for item in state.get("history", []) if item != digest and (modules / (item + ".pvm")).exists()
    ]
    history = history[:2]
    new_state = {
        "format": 1,
        "application_id": args.app_id,
        "channel": args.channel,
        "platform": args.platform,
        "profile": args.profile,
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
        state = read_bound_state(args.cache.resolve() / "current.json", args)
        cached = cached_module(state, args)
        if cached is not None:
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
