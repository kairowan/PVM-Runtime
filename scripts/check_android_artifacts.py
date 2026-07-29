#!/usr/bin/env python3
"""Validate the Android demo packages and reusable Runtime artifact."""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "android"
APK = DIST / "PVMRuntime-demo-debug.apk"
AAB = DIST / "PVMRuntime-demo-debug.aab"
MINIFIED_APK = DIST / "PVMRuntime-demo-minified-smoke.apk"
AAR = DIST / "pvm-runtime-0.5.0.aar"
MAVEN_AAR = (
    DIST
    / "maven/com/protectedvm/pvm-runtime/0.5.0/pvm-runtime-0.5.0.aar"
)
POM = (
    DIST
    / "maven/com/protectedvm/pvm-runtime/0.5.0/pvm-runtime-0.5.0.pom"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, expect_success=True):
    result = subprocess.run(
        [str(value) for value in command],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    require(
        (result.returncode == 0) == expect_success,
        f"unexpected exit from {' '.join(map(str, command))}:\n{result.stdout}",
    )
    return result.stdout


def find_sdk():
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(Path.home() / "Library/Android/sdk"),
        str(Path.home() / "Desktop/android/sdk"),
    ]
    return next(
        (Path(value) for value in candidates if value and Path(value).is_dir()),
        None,
    )


def find_build_tool(name):
    sdk = find_sdk()
    require(sdk is not None, "Android SDK was not found")
    versions = [
        path
        for path in (sdk / "build-tools").iterdir()
        if path.is_dir()
        and re.fullmatch(r"\d+(?:\.\d+)*", path.name)
        and (path / name).is_file()
    ]
    require(versions, f"No stable Android build-tools installation provides {name}")
    latest = max(versions, key=lambda path: tuple(map(int, path.name.split("."))))
    return latest / name


def delivery_from(archive, prefix):
    names = set(archive.namelist())
    required = {
        f"{prefix}assets/bootstrap.json",
        f"{prefix}assets/module-public-key.pem",
        f"{prefix}assets/module.pvm",
        f"{prefix}lib/arm64-v8a/libpvm_android.so",
        f"{prefix}lib/x86_64/libpvm_android.so",
    }
    require(required <= names, f"Android delivery entries are missing: {required - names}")
    require(
        not any("private" in name.lower() or name.endswith((".jks", ".keystore")) for name in names),
        "Android package contains private signing material",
    )
    return {
        "bootstrap": archive.read(f"{prefix}assets/bootstrap.json"),
        "key": archive.read(f"{prefix}assets/module-public-key.pem"),
        "module": archive.read(f"{prefix}assets/module.pvm"),
    }


def validate_delivery(delivery):
    bootstrap = json.loads(delivery["bootstrap"])
    require(bootstrap["platform"] == "android", "bootstrap platform is not android")
    require(bootstrap["profile"] == "offline_sealed", "bootstrap profile is not offline_sealed")
    require(bootstrap["mode"] == "bundled", "bootstrap mode is not bundled")
    require(set(bootstrap["packageFormats"]) == {"apk", "aab"}, "package formats drifted")
    require(
        hashlib.sha256(delivery["module"]).hexdigest() == bootstrap["sha256"],
        "bundled module SHA-256 does not match bootstrap",
    )
    module = delivery["module"]
    require(len(module) >= 14 and module[:4] == b"PVMP", "invalid PVM package header")
    payload_size = struct.unpack_from("<I", module, 8)[0]
    signature_size = struct.unpack_from("<H", module, 12)[0]
    require(signature_size == 64, "PVM package does not use a 64-byte Ed25519 signature")
    require(
        14 + payload_size + signature_size == len(module),
        "PVM package length fields are inconsistent",
    )
    require(
        b"BEGIN PRIVATE KEY" not in delivery["key"],
        "public key asset contains a private key",
    )
    return bootstrap


def validate_runtime_aar():
    require(AAR.read_bytes() == MAVEN_AAR.read_bytes(), "Maven and standalone AARs differ")
    with zipfile.ZipFile(AAR) as archive:
        names = set(archive.namelist())
        required = {
            "AndroidManifest.xml",
            "classes.jar",
            "jni/arm64-v8a/libpvm_android.so",
            "jni/x86_64/libpvm_android.so",
        }
        require(required <= names, f"Runtime AAR entries are missing: {required - names}")
        require(str(ROOT).encode() not in AAR.read_bytes(), "Release AAR leaks the local source path")
        for abi in ("arm64-v8a", "x86_64"):
            validate_elf_alignment(
                archive.read(f"jni/{abi}/libpvm_android.so"),
                abi,
            )
        with zipfile.ZipFile(BytesIO(archive.read("classes.jar"))) as classes:
            class_names = set(classes.namelist())
            require(
                {
                    "com/protectedvm/host/PvmRuntimeHost.class",
                    "com/protectedvm/host/PvmCrypto.class",
                }
                <= class_names,
                "Runtime AAR is missing its Kotlin host classes",
            )
    pom = POM.read_text(encoding="utf-8")
    require("<artifactId>tink-android</artifactId>" in pom, "Runtime POM lost Ed25519 dependency")


def validate_elf_alignment(binary, abi):
    require(
        binary[:6] == b"\x7fELF\x02\x01",
        f"{abi} Runtime library is not a little-endian ELF64 binary",
    )
    program_offset = struct.unpack_from("<Q", binary, 32)[0]
    entry_size = struct.unpack_from("<H", binary, 54)[0]
    entry_count = struct.unpack_from("<H", binary, 56)[0]
    alignments = []
    for index in range(entry_count):
        offset = program_offset + index * entry_size
        if struct.unpack_from("<I", binary, offset)[0] == 1:
            alignments.append(struct.unpack_from("<Q", binary, offset + 48)[0])
    require(alignments, f"{abi} Runtime library has no PT_LOAD segments")
    require(
        min(alignments) >= 0x4000,
        f"{abi} Runtime LOAD alignment is below 16 KiB: {alignments}",
    )


def validate_with_runtime(delivery, bootstrap):
    runtime = ROOT / "build/client/pvm_cli"
    require(runtime.is_file(), "build/client/pvm_cli is required for package validation")
    with tempfile.TemporaryDirectory(prefix="pvm-android-check-") as directory:
        temporary = Path(directory)
        module = temporary / "module.pvm"
        key = temporary / "module-public-key.pem"
        module.write_bytes(delivery["module"])
        key.write_bytes(delivery["key"])
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
            "--validate-only",
        ]
        run(command)
        tampered = bytearray(delivery["module"])
        tampered[-1] ^= 1
        module.write_bytes(tampered)
        run(command, expect_success=False)


def main():
    for artifact in (APK, AAB, MINIFIED_APK, AAR, MAVEN_AAR, POM):
        require(artifact.is_file(), f"Android artifact is missing: {artifact}")
    with zipfile.ZipFile(APK) as apk, zipfile.ZipFile(AAB) as aab, zipfile.ZipFile(
        MINIFIED_APK
    ) as minified:
        apk_delivery = delivery_from(apk, "")
        aab_delivery = delivery_from(aab, "base/")
        minified_delivery = delivery_from(minified, "")
        aab_entries = set(aab.namelist())
    require(
        any(name.startswith("META-INF/") and name.endswith(".SF") for name in aab_entries)
        and any(
            name.startswith("META-INF/") and name.endswith((".RSA", ".DSA", ".EC"))
            for name in aab_entries
        ),
        "AAB has no JAR signature",
    )
    jarsigner = shutil.which("jarsigner")
    require(jarsigner is not None, "JDK jarsigner was not found")
    run([jarsigner, "-verify", AAB])
    require(
        apk_delivery == aab_delivery == minified_delivery,
        "Android packages embed different delivery inputs",
    )
    bootstrap = validate_delivery(apk_delivery)
    validate_runtime_aar()
    validate_with_runtime(apk_delivery, bootstrap)

    badging = run([find_build_tool("aapt"), "dump", "badging", APK])
    require("package: name='com.example.protected'" in badging, "APK package name drifted")
    require("sdkVersion:'33'" in badging and "targetSdkVersion:'36'" in badging, "APK SDK levels drifted")
    require("application-debuggable" in badging, "Demo artifact is expected to be a debug APK")
    require(
        "native-code: 'arm64-v8a' 'x86_64'" in badging,
        "APK ABI declaration drifted",
    )
    run([find_build_tool("zipalign"), "-c", "-P", "16", "4", APK])
    signing = run([find_build_tool("apksigner"), "verify", "--print-certs", APK])
    require("CN=Android Debug" in signing, "Demo APK is not signed by the debug key")

    minified_badging = run([find_build_tool("aapt"), "dump", "badging", MINIFIED_APK])
    require(
        "package: name='com.example.protected'" in minified_badging
        and "application-debuggable" not in minified_badging,
        "R8 smoke APK is not a non-debuggable build",
    )
    run([find_build_tool("zipalign"), "-c", "-P", "16", "4", MINIFIED_APK])
    minified_signing = run(
        [find_build_tool("apksigner"), "verify", "--print-certs", MINIFIED_APK]
    )
    require("CN=Android Debug" in minified_signing, "R8 smoke APK lost its test signature")

    print(
        "Android artifacts: PASS "
        "(APK + AAB + AAR/Maven + R8 smoke, signature, ABI, assets, tamper rejection)"
    )


if __name__ == "__main__":
    main()
