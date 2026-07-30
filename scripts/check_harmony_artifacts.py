#!/usr/bin/env python3
"""Validate the HarmonyOS HAR, unsigned emulator HAP, and bundled delivery."""

import hashlib
import json
import shlex
import struct
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "harmony"
HAR = DIST / "pvm-runtime-0.5.0.har"
HAP = DIST / "PVMRuntime-demo-unsigned.hap"
DELIVERY = ROOT / "build" / "delivery" / "client" / "harmonyos" / "offline_sealed"
DELIVERY_FILES = ("bootstrap.json", "module-public-key.pem", "module.pvm")
CRYPTO_SOURCE = (
    ROOT / "client/platform/harmony/runtime/src/main/ets/pvm/HarmonyCrypto.ets"
)
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


def fail(message):
    raise SystemExit(f"HarmonyOS artifact check failed: {message}")


def require(condition, message):
    if not condition:
        fail(message)


def run(command, *, expect_success=True):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    require(
        (result.returncode == 0) == expect_success,
        f"unexpected exit from {shlex.join(command)}:\n{result.stdout}",
    )
    return result.stdout


def safe_archive_name(name):
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def check_sensitive(name, content):
    require(
        not any(marker in content for marker in PRIVATE_KEY_MARKERS),
        f"private signing material found in {name}",
    )
    local_paths = (
        str(ROOT).encode(),
        b"/tmp/pvm-harmony-build-",
        b"/private/tmp/pvm-harmony-build-",
    )
    require(
        not any(path in content for path in local_paths),
        f"local build path found in {name}",
    )


def check_elf(content, abi):
    expected_machine = {"arm64-v8a": 183, "x86_64": 62}[abi]
    require(
        len(content) >= 64 and content[:6] == b"\x7fELF\x02\x01",
        f"{abi} Runtime is not a little-endian ELF64 binary",
    )
    require(struct.unpack_from("<H", content, 16)[0] == 3, f"{abi} Runtime is not ET_DYN")
    require(
        struct.unpack_from("<H", content, 18)[0] == expected_machine,
        f"{abi} Runtime has the wrong machine type",
    )


def has_hap_signing_block(content):
    end_of_directory = content.rfind(b"PK\x05\x06")
    require(end_of_directory >= 0, "HAP ZIP end-of-central-directory record is missing")
    require(
        end_of_directory + 20 <= len(content),
        "HAP ZIP end-of-central-directory record is truncated",
    )
    central_directory = struct.unpack_from("<I", content, end_of_directory + 16)[0]
    require(central_directory <= len(content), "HAP central-directory offset is invalid")
    tail = content[max(0, central_directory - 32) : central_directory]
    magics = (b"HAP Sig Block 42", b"<hap sign block>")
    return any(tail.endswith(magic) or tail[-20:-4] == magic for magic in magics)


def check_source_contracts():
    source = CRYPTO_SOURCE.read_text(encoding="utf-8")
    require(
        source.count("createAsyKeyGenerator('Ed25519')") == 1
        and source.count("createVerify('Ed25519')") == 1
        and "'ED25519'" not in source,
        "HarmonyOS CryptoFramework requires the case-sensitive Ed25519 algorithm token",
    )


def read_har():
    require(HAR.is_file(), f"missing {HAR}")
    contents = {}
    try:
        with tarfile.open(HAR, "r:gz") as archive:
            for member in archive.getmembers():
                require(safe_archive_name(member.name), f"unsafe HAR path: {member.name}")
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                require(stream is not None, f"cannot read HAR entry: {member.name}")
                contents[member.name] = stream.read()
    except tarfile.TarError as error:
        fail(f"invalid HAR: {error}")
    required = {
        "package/Index.d.ets",
        "package/ets/modules.abc",
        "package/oh-package.json5",
        "package/libs/arm64-v8a/libpvm_harmony.so",
        "package/libs/x86_64/libpvm_harmony.so",
    }
    require(required <= contents.keys(), f"HAR entries are missing: {required - contents.keys()}")
    metadata = json.loads(contents["package/oh-package.json5"])
    require(metadata.get("name") == "@pvm/runtime", "HAR package name drifted")
    require(metadata.get("version") == "0.5.0", "HAR version drifted")
    require(metadata.get("compatibleSdkVersion") == 23, "HAR compatible API drifted")
    require(
        metadata.get("metadata", {}).get("debug") is False,
        "HAR must be a release build",
    )
    for name, content in contents.items():
        check_sensitive(f"HAR:{name}", content)
    return {
        abi: contents[f"package/libs/{abi}/libpvm_harmony.so"]
        for abi in ("arm64-v8a", "x86_64")
    }


def read_hap():
    require(HAP.is_file(), f"missing {HAP}")
    raw = HAP.read_bytes()
    require(not has_hap_signing_block(raw), "emulator HAP is unexpectedly signed")
    try:
        with zipfile.ZipFile(HAP) as archive:
            names = set(archive.namelist())
            for name in names:
                require(safe_archive_name(name), f"unsafe HAP path: {name}")
            required = {
                "module.json",
                "ets/modules.abc",
                "libs/arm64-v8a/libpvm_harmony.so",
                "libs/x86_64/libpvm_harmony.so",
                *(f"resources/rawfile/{name}" for name in DELIVERY_FILES),
            }
            require(required <= names, f"HAP entries are missing: {required - names}")
            contents = {name: archive.read(name) for name in names if not name.endswith("/")}
    except zipfile.BadZipFile as error:
        fail(f"invalid HAP: {error}")
    for name, content in contents.items():
        check_sensitive(f"HAP:{name}", content)
    return contents


def check_delivery(hap):
    source = {}
    for name in DELIVERY_FILES:
        path = DELIVERY / name
        require(path.is_file(), f"delivery input is missing: {path}")
        source[name] = path.read_bytes()
        require(
            hap[f"resources/rawfile/{name}"] == source[name],
            f"HAP embeds a stale {name}",
        )

    bootstrap = json.loads(source["bootstrap.json"])
    expected = {
        "applicationId": "com.example.protected",
        "channel": "enterprise",
        "mode": "bundled",
        "packageFormats": ["hap"],
        "platform": "harmonyos",
        "profile": "offline_sealed",
        "publicKey": "module-public-key.pem",
        "release": 5,
    }
    require(
        all(bootstrap.get(key) == value for key, value in expected.items()),
        "bootstrap does not match the HarmonyOS Offline Sealed demo",
    )
    require(
        hashlib.sha256(source["module.pvm"]).hexdigest() == bootstrap.get("sha256"),
        "bootstrap SHA-256 does not match module.pvm",
    )
    module = source["module.pvm"]
    require(len(module) >= 14 and module[:4] == b"PVMP", "invalid PVM package header")
    payload_size = struct.unpack_from("<I", module, 8)[0]
    signature_size = struct.unpack_from("<H", module, 12)[0]
    require(signature_size == 64, "PVM package is not Ed25519-signed")
    require(
        14 + payload_size + signature_size == len(module),
        "PVM package length fields are inconsistent",
    )
    require(
        b"BEGIN PUBLIC KEY" in source["module-public-key.pem"]
        and not any(marker in source["module-public-key.pem"] for marker in PRIVATE_KEY_MARKERS),
        "delivery key is not a public PEM",
    )
    return source, bootstrap


def check_module_metadata(hap):
    metadata = json.loads(hap["module.json"])
    app = metadata.get("app", {})
    module = metadata.get("module", {})
    require(app.get("bundleName") == "com.example.protected", "HAP bundle name drifted")
    require(app.get("versionName") == "0.5.0", "HAP version drifted")
    require(app.get("debug") is False, "HAP must be a release build")
    require(app.get("minAPIVersion") == 60100023, "HAP compatible API drifted")
    require(app.get("targetAPIVersion") == 60101024, "HAP target API drifted")
    require(
        module.get("name") == "demo"
        and module.get("type") == "entry"
        and module.get("mainElement") == "EntryAbility",
        "HAP entry module metadata drifted",
    )


def validate_with_runtime(delivery, bootstrap):
    runtime = ROOT / "build/client/pvm_cli"
    require(runtime.is_file(), "build/client/pvm_cli is required for package validation")
    with tempfile.TemporaryDirectory(prefix="pvm-harmony-check-") as name:
        temporary = Path(name)
        module = temporary / "module.pvm"
        key = temporary / "module-public-key.pem"
        module.write_bytes(delivery["module.pvm"])
        key.write_bytes(delivery["module-public-key.pem"])
        command = [
            runtime,
            "--module",
            module,
            "--public-key",
            key,
            "--app-id",
            bootstrap["applicationId"],
            "--min-release",
            bootstrap["release"],
            "--channel",
            bootstrap["channel"],
            "--platform",
            bootstrap["platform"],
            "--profile",
            bootstrap["profile"],
            "--validate-only",
        ]
        run(command)
        tampered = bytearray(delivery["module.pvm"])
        tampered[-1] ^= 1
        module.write_bytes(tampered)
        run(command, expect_success=False)


def main():
    check_source_contracts()
    har_libraries = read_har()
    hap = read_hap()
    for abi, har_library in har_libraries.items():
        hap_library = hap[f"libs/{abi}/libpvm_harmony.so"]
        require(har_library == hap_library, f"HAR and HAP contain different {abi} Runtime")
        check_elf(har_library, abi)
    delivery, bootstrap = check_delivery(hap)
    check_module_metadata(hap)
    validate_with_runtime(delivery, bootstrap)
    print(
        "HarmonyOS artifacts: PASS "
        "(release HAR + unsigned emulator HAP, API 23/24, arm64/x86_64, "
        "delivery hash/signature, tamper rejection)"
    )


if __name__ == "__main__":
    main()
