#!/usr/bin/env python3
"""Build the complete precompiled iOS Runtime as a distributable XCFramework."""

import os
import plistlib
import shlex
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "ios-sdk"
OUTPUT = ROOT / "dist" / "ios" / "PVMRuntime.xcframework"
LEGACY_OUTPUT = ROOT / "dist" / "ios" / "PVMBridge.xcframework"
VERSION = "0.5.0"
SOURCES = (
    ("runtime", "client/src/runtime.cpp", False),
    ("c_api", "client/src/c_api.cpp", False),
    ("bridge", "client/platform/ios/PVMRuntimeBridge.mm", True),
)
VARIANTS = (
    ("device", "iphoneos", "arm64-apple-ios15.0", "arm64-apple-ios"),
    (
        "sim-arm64",
        "iphonesimulator",
        "arm64-apple-ios15.0-simulator",
        "arm64-apple-ios-simulator",
    ),
    (
        "sim-x86_64",
        "iphonesimulator",
        "x86_64-apple-ios15.0-simulator",
        "x86_64-apple-ios-simulator",
    ),
)
SWIFT_SOURCES = tuple(sorted((ROOT / "client/platform/ios/swift").glob("*.swift")))


def run(command, *, capture=False):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "ZERO_AR_DATE": "1"},
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    ).stdout


def reset_generated(path):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def compile_native_variant(name, sdk_name, target):
    destination = BUILD / name
    destination.mkdir()
    sdk = run(["xcrun", "--sdk", sdk_name, "--show-sdk-path"], capture=True).strip()
    common = [
        "-target",
        target,
        "-isysroot",
        sdk,
        "-std=c++17",
        "-O2",
        "-DNDEBUG",
        "-DPVM_USE_OPENSSL=0",
        "-fvisibility=hidden",
        "-fvisibility-inlines-hidden",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-Iclient/include",
        "-Iclient/platform/ios/include",
    ]
    objects = []
    for stem, source, objective_c in SOURCES:
        output = destination / f"{stem}.o"
        flags = ["-fobjc-arc", "-fblocks"] if objective_c else []
        run(
            [
                "xcrun",
                "--sdk",
                sdk_name,
                "clang++",
                *common,
                *flags,
                "-c",
                source,
                "-o",
                output,
            ]
        )
        objects.append(output)
    archive = destination / "libPVMBridge.a"
    run(["xcrun", "libtool", "-static", "-o", archive, *objects])
    return archive


def write_framework_plist(framework, sdk_name):
    supported_platform = (
        "iPhoneOS" if sdk_name == "iphoneos" else "iPhoneSimulator"
    )
    with (framework / "Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleDevelopmentRegion": "en",
                "CFBundleExecutable": "PVMRuntime",
                "CFBundleIdentifier": "com.protectedvm.PVMRuntime",
                "CFBundleInfoDictionaryVersion": "6.0",
                "CFBundleName": "PVMRuntime",
                "CFBundlePackageType": "FMWK",
                "CFBundleShortVersionString": VERSION,
                "CFBundleSupportedPlatforms": [supported_platform],
                "CFBundleVersion": "1",
                "MinimumOSVersion": "15.0",
            },
            stream,
            sort_keys=True,
        )


def compile_swift_variant(name, sdk_name, target, module_triple, native):
    framework = BUILD / "frameworks" / name / "PVMRuntime.framework"
    modules = framework / "Modules" / "PVMRuntime.swiftmodule"
    modules.mkdir(parents=True)
    sdk = run(["xcrun", "--sdk", sdk_name, "--show-sdk-path"], capture=True).strip()
    run(
        [
            "xcrun",
            "--sdk",
            sdk_name,
            "swiftc",
            "-target",
            target,
            "-sdk",
            sdk,
            "-swift-version",
            "6",
            "-strict-concurrency=complete",
            "-warnings-as-errors",
            "-parse-as-library",
            "-O",
            "-enable-library-evolution",
            "-emit-library",
            "-emit-module",
            "-module-name",
            "PVMRuntime",
            "-emit-module-path",
            modules / f"{module_triple}.swiftmodule",
            "-emit-module-interface-path",
            modules / f"{module_triple}.swiftinterface",
            "-emit-private-module-interface-path",
            modules / f"{module_triple}.private.swiftinterface",
            "-I",
            BUILD / "headers",
            "-L",
            native.parent,
            "-lPVMBridge",
            "-Xlinker",
            "-install_name",
            "-Xlinker",
            "@rpath/PVMRuntime.framework/PVMRuntime",
            "-Xlinker",
            "-compatibility_version",
            "-Xlinker",
            "1.0.0",
            "-Xlinker",
            "-current_version",
            "-Xlinker",
            VERSION,
            "-framework",
            "Foundation",
            "-framework",
            "UIKit",
            "-framework",
            "SwiftUI",
            "-framework",
            "Combine",
            "-framework",
            "CryptoKit",
            *SWIFT_SOURCES,
            "-o",
            framework / "PVMRuntime",
        ]
    )
    for source_info in modules.glob("*.swiftsourceinfo"):
        source_info.unlink()
    shutil.copy2(
        ROOT / "client/platform/ios/swift/PrivacyInfo.xcprivacy",
        framework / "PrivacyInfo.xcprivacy",
    )
    write_framework_plist(framework, sdk_name)
    return framework


def merge_simulator_framework(arm64, x86_64):
    simulator = BUILD / "frameworks" / "simulator" / "PVMRuntime.framework"
    shutil.copytree(arm64, simulator)
    run(
        [
            "xcrun",
            "lipo",
            "-create",
            arm64 / "PVMRuntime",
            x86_64 / "PVMRuntime",
            "-output",
            simulator / "PVMRuntime",
        ]
    )
    destination = simulator / "Modules/PVMRuntime.swiftmodule"
    for source in (x86_64 / "Modules/PVMRuntime.swiftmodule").iterdir():
        shutil.copy2(source, destination / source.name)
    return simulator


def main():
    for _, source, _ in SOURCES:
        if not (ROOT / source).is_file():
            raise SystemExit(f"Missing iOS SDK source: {source}")
    reset_generated(BUILD)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    for output in (OUTPUT, LEGACY_OUTPUT):
        if output.exists():
            shutil.rmtree(output)

    archives = {
        name: compile_native_variant(name, sdk, target)
        for name, sdk, target, _ in VARIANTS
    }

    headers = BUILD / "headers"
    headers.mkdir()
    for name in ("PVMRuntimeBridge.h", "module.modulemap"):
        shutil.copyfile(ROOT / "client/platform/ios/include" / name, headers / name)

    frameworks = {
        name: compile_swift_variant(
            name,
            sdk,
            target,
            module_triple,
            archives[name],
        )
        for name, sdk, target, module_triple in VARIANTS
    }
    simulator = merge_simulator_framework(
        frameworks["sim-arm64"],
        frameworks["sim-x86_64"],
    )
    run(
        [
            "xcodebuild",
            "-create-xcframework",
            "-framework",
            frameworks["device"],
            "-framework",
            simulator,
            "-output",
            OUTPUT,
        ]
    )
    print(f"XCFramework: {OUTPUT}")


if __name__ == "__main__":
    main()
