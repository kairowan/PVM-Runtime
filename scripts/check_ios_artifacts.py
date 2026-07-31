#!/usr/bin/env python3
"""Validate the complete binary iOS Runtime and its Swift consumer boundary."""

import json
import plistlib
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "dist" / "ios" / "PVMRuntime.xcframework"
CHECK_BUILD = ROOT / "build" / "ios-sdk" / "check"
EXPECTED = {
    ("ios", None): ({"arm64"}, "2", ("arm64-apple-ios",)),
    (
        "ios",
        "simulator",
    ): (
        {"arm64", "x86_64"},
        "7",
        ("arm64-apple-ios-simulator", "x86_64-apple-ios-simulator"),
    ),
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


def check_deployment_target(binary, expected_platform):
    output = run(["otool", "-l", binary])
    versions = re.findall(
        r"cmd LC_BUILD_VERSION\s+cmdsize \d+\s+platform (\d+)\s+minos ([0-9.]+)",
        output,
    )
    if not versions:
        fail(f"missing LC_BUILD_VERSION in {binary}")
    for platform, minimum in versions:
        if platform != expected_platform or minimum != "15.0":
            fail(
                f"{binary} has platform/minimum {platform}/{minimum}; "
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


def check_framework(entry, expected):
    expected_architectures, expected_platform, module_triples = expected
    framework = contained(ARTIFACT / entry["LibraryIdentifier"], entry["LibraryPath"])
    binary = framework / "PVMRuntime"
    if not framework.is_dir() or not binary.is_file():
        fail(f"missing PVMRuntime framework for {entry['LibraryIdentifier']}")

    with (framework / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if (
        info.get("CFBundleIdentifier") != "com.protectedvm.PVMRuntime"
        or info.get("CFBundleShortVersionString") != "0.6.0"
        or info.get("MinimumOSVersion") != "15.0"
    ):
        fail(f"invalid framework metadata for {entry['LibraryIdentifier']}")
    if not (framework / "PrivacyInfo.xcprivacy").is_file():
        fail(f"missing Privacy Manifest for {entry['LibraryIdentifier']}")

    architectures = set(run(["xcrun", "lipo", "-archs", binary]).split())
    if architectures != expected_architectures:
        fail(f"binary architecture mismatch: {architectures}")
    check_deployment_target(binary, expected_platform)
    linked = run(["otool", "-L", binary])
    if (
        "@rpath/PVMRuntime.framework/PVMRuntime" not in linked
        or "/usr/lib/libc++.1.dylib" not in linked
    ):
        fail(f"invalid framework linkage for {entry['LibraryIdentifier']}")
    symbols = run(["nm", "-gU", binary])
    if "_pvm_runtime_create_v3" not in symbols or "PVMHost" not in symbols:
        fail(f"Runtime or Swift Host symbol missing for {entry['LibraryIdentifier']}")

    modules = framework / "Modules/PVMRuntime.swiftmodule"
    for triple in module_triples:
        interface = modules / f"{triple}.swiftinterface"
        if not interface.is_file():
            fail(f"missing stable Swift interface for {triple}")
        contents = interface.read_text(encoding="utf-8")
        if "class PVMHost" not in contents or "import PVMBridge" in contents:
            fail(f"invalid public Swift interface for {triple}")
    return framework


def check_swift_consumer(simulator_framework):
    sdk = run(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"]).strip()
    package = json.loads(run(["swift", "package", "describe", "--type", "json"]))
    target_names = {target["name"] for target in package.get("targets", [])}
    if package.get("name") != "PVMRuntime" or not {
        "PVMCore",
        "PVMBridge",
        "PVMRuntime",
    } <= target_names:
        fail("source Swift Package targets are incomplete")

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
            "-parse-as-library",
            "-F",
            simulator_framework.parent,
            "-typecheck",
            "client/platform/ios/demo/AppDelegate.swift",
        ]
    )

    CHECK_BUILD.mkdir(parents=True, exist_ok=True)
    probe = CHECK_BUILD / "PVMRuntimeConsumer.swift"
    probe.write_text(
        "import PVMRuntime\n"
        "public func pvmRuntimeConsumerProbe(_ policy: PVMRuntimePolicy) -> String {\n"
        "    policy.platform\n"
        "}\n",
        encoding="utf-8",
    )
    consumer = CHECK_BUILD / "libPVMRuntimeConsumer.dylib"
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
            "-F",
            simulator_framework.parent,
            "-framework",
            "PVMRuntime",
            probe,
            "-o",
            consumer,
        ]
    )
    if "arm64" not in run(["file", consumer]):
        fail("binary Swift consumer is not arm64")
    if "@rpath/PVMRuntime.framework/PVMRuntime" not in run(["otool", "-L", consumer]):
        fail("binary Swift consumer did not link PVMRuntime.framework")


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
        framework = check_framework(entry, EXPECTED[key])
        if key[1] == "simulator":
            simulator = framework

    if found != set(EXPECTED) or simulator is None:
        fail("required device/simulator slices are incomplete")
    check_sensitive_content()
    check_swift_consumer(simulator)
    print(
        "iOS artifact: PASS "
        "(complete binary Runtime, arm64 device + arm64/x86_64 simulator, iOS 15)"
    )


if __name__ == "__main__":
    main()
