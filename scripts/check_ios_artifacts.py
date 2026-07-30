#!/usr/bin/env python3
"""Validate the distributable iOS XCFramework and its Swift consumer boundary."""

import json
import plistlib
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "dist" / "ios" / "PVMBridge.xcframework"
CHECK_BUILD = ROOT / "build" / "ios-sdk" / "check"
SOURCE_HEADERS = ROOT / "client" / "platform" / "ios" / "include"
SWIFT_SOURCES = sorted((ROOT / "client/platform/ios/swift").glob("*.swift"))
EXPECTED = {
    ("ios", None): ({"arm64"}, "2"),
    ("ios", "simulator"): ({"arm64", "x86_64"}, "7"),
}
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


def fail(message):
    raise SystemExit(f"iOS artifact check failed: {message}")


def run(command):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def contained(base, relative):
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        fail(f"path escapes XCFramework: {relative}")
    return candidate


def check_deployment_target(library, expected_platform):
    output = run(["otool", "-l", library])
    versions = re.findall(
        r"cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform (\d+)\s+minos ([0-9.]+)",
        output,
    )
    if not versions:
        fail(f"missing LC_BUILD_VERSION in {library}")
    for platform, minimum in versions:
        if platform != expected_platform or minimum != "15.0":
            fail(
                f"{library} has platform/minimum {platform}/{minimum}; "
                f"expected {expected_platform}/15.0"
            )


def check_sensitive_content():
    local_paths = {
        str(ROOT).encode(),
        str(Path.home()).encode(),
        b"/var/folders/",
        b"/private/tmp/",
    }
    banned_suffixes = {
        ".jks",
        ".key",
        ".keystore",
        ".mobileprovision",
        ".pem",
        ".pvm",
    }
    for path in ARTIFACT.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() in banned_suffixes:
            fail(f"unexpected sensitive artifact: {path.relative_to(ARTIFACT)}")
        content = path.read_bytes()
        if any(marker in content for marker in PRIVATE_KEY_MARKERS):
            fail(f"private key material found in {path.relative_to(ARTIFACT)}")
        if any(value and value in content for value in local_paths):
            fail(f"local absolute path found in {path.relative_to(ARTIFACT)}")


def check_swift(simulator_library, simulator_headers):
    sdk = run(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"]).strip()
    package = json.loads(run(["swift", "package", "describe", "--type", "json"]))
    target_names = {target["name"] for target in package.get("targets", [])}
    if package.get("name") != "PVMRuntime" or not {"PVMCore", "PVMBridge", "PVMRuntime"} <= target_names:
        fail("Swift Package targets are incomplete")
    run(
        [
            "xcrun",
            "--sdk",
            "iphonesimulator",
            "swiftc",
            "-target",
            "arm64-apple-ios15.0-simulator",
            "-sdk",
            sdk,
            "-swift-version",
            "6",
            "-strict-concurrency=complete",
            "-warnings-as-errors",
            "-I",
            simulator_headers,
            "-typecheck",
            *SWIFT_SOURCES,
        ]
    )
    run(
        [
            "xcodebuild",
            "-quiet",
            "-scheme",
            "PVMRuntime",
            "-destination",
            "generic/platform=iOS Simulator",
            "-derivedDataPath",
            ROOT / "build/ios-sdk/package",
            "CODE_SIGNING_ALLOWED=NO",
            "SWIFT_VERSION=6",
            "SWIFT_STRICT_CONCURRENCY=complete",
            "SWIFT_TREAT_WARNINGS_AS_ERRORS=YES",
            "build",
        ]
    )

    CHECK_BUILD.mkdir(parents=True, exist_ok=True)
    probe = CHECK_BUILD / "PVMBridgeConsumer.swift"
    probe.write_text(
        "import PVMBridge\n"
        "public func pvmBridgeConsumerProbe(_ bridge: PVMRuntimeBridge) -> UInt64 {\n"
        "    bridge.moduleRelease\n"
        "}\n",
        encoding="utf-8",
    )
    consumer = CHECK_BUILD / "libPVMBridgeConsumer.dylib"
    run(
        [
            "xcrun",
            "--sdk",
            "iphonesimulator",
            "swiftc",
            "-target",
            "arm64-apple-ios15.0-simulator",
            "-sdk",
            sdk,
            "-parse-as-library",
            "-emit-library",
            "-module-name",
            "PVMBridgeConsumer",
            "-I",
            simulator_headers,
            "-L",
            simulator_library.parent,
            "-lPVMBridge",
            probe,
            "-o",
            consumer,
        ]
    )
    if "arm64" not in run(["file", consumer]):
        fail("Swift XCFramework consumer is not an arm64 simulator binary")
    unresolved = run(["nm", "-u", consumer])
    if "_pvm_" in unresolved:
        fail("Swift XCFramework consumer has unresolved PVM symbols")


def main():
    info = ARTIFACT / "Info.plist"
    if not info.is_file():
        fail(f"missing {info}")
    with info.open("rb") as stream:
        libraries = plistlib.load(stream).get("AvailableLibraries", [])
    if len(libraries) != len(EXPECTED):
        fail(f"expected two slices, found {len(libraries)}")

    found = set()
    simulator = None
    for entry in libraries:
        key = (entry.get("SupportedPlatform"), entry.get("SupportedPlatformVariant"))
        if key not in EXPECTED or key in found:
            fail(f"unexpected or duplicate slice: {key}")
        found.add(key)
        expected_architectures, expected_platform = EXPECTED[key]
        if set(entry.get("SupportedArchitectures", [])) != expected_architectures:
            fail(f"Info.plist architecture mismatch for {key}")
        library = contained(
            ARTIFACT / entry["LibraryIdentifier"],
            entry["LibraryPath"],
        )
        headers = contained(
            ARTIFACT / entry["LibraryIdentifier"],
            entry["HeadersPath"],
        )
        if not library.is_file() or library.suffix != ".a":
            fail(f"missing static library for {key}")
        for name in ("PVMRuntimeBridge.h", "module.modulemap"):
            packaged = headers / name
            if not packaged.is_file():
                fail(f"missing public header {name} for {key}")
            if packaged.read_bytes() != (SOURCE_HEADERS / name).read_bytes():
                fail(f"stale public header {name} for {key}")
        architectures = set(run(["xcrun", "lipo", "-archs", library]).split())
        if architectures != expected_architectures:
            fail(f"binary architecture mismatch for {key}: {architectures}")
        check_deployment_target(library, expected_platform)
        symbols = run(["nm", "-g", library])
        if (
            "_pvm_runtime_create_v3" not in symbols
            or "_OBJC_CLASS_$_PVMRuntimeBridge" not in symbols
        ):
            fail(f"Runtime or Objective-C bridge symbol missing for {key}")
        if key[1] == "simulator":
            simulator = (library, headers)

    if found != set(EXPECTED) or simulator is None:
        fail("required device/simulator slices are incomplete")
    check_sensitive_content()
    check_swift(*simulator)
    print(
        "iOS artifact: PASS "
        "(arm64 device + arm64/x86_64 simulator, iOS 15, Swift Package + Swift 6 consumer)"
    )


if __name__ == "__main__":
    main()
