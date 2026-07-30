#!/usr/bin/env python3
"""Build the native iOS Runtime bridge as a static XCFramework."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "ios-sdk"
OUTPUT = ROOT / "dist" / "ios" / "PVMBridge.xcframework"
SOURCES = (
    ("runtime", "client/src/runtime.cpp", False),
    ("c_api", "client/src/c_api.cpp", False),
    ("bridge", "client/platform/ios/PVMRuntimeBridge.mm", True),
)
VARIANTS = (
    ("device", "iphoneos", "arm64-apple-ios15.0"),
    ("sim-arm64", "iphonesimulator", "arm64-apple-ios15.0-simulator"),
    ("sim-x86_64", "iphonesimulator", "x86_64-apple-ios15.0-simulator"),
)


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


def compile_variant(name, sdk_name, target):
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


def main():
    for _, source, _ in SOURCES:
        if not (ROOT / source).is_file():
            raise SystemExit(f"Missing iOS SDK source: {source}")
    reset_generated(BUILD)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)

    archives = {
        name: compile_variant(name, sdk, target)
        for name, sdk, target in VARIANTS
    }
    simulator = BUILD / "simulator" / "libPVMBridge.a"
    simulator.parent.mkdir()
    run(
        [
            "xcrun",
            "lipo",
            "-create",
            archives["sim-arm64"],
            archives["sim-x86_64"],
            "-output",
            simulator,
        ]
    )

    headers = BUILD / "headers"
    headers.mkdir()
    for name in ("PVMRuntimeBridge.h", "module.modulemap"):
        shutil.copyfile(ROOT / "client/platform/ios/include" / name, headers / name)
    run(
        [
            "xcodebuild",
            "-create-xcframework",
            "-library",
            archives["device"],
            "-headers",
            headers,
            "-library",
            simulator,
            "-headers",
            headers,
            "-output",
            OUTPUT,
        ]
    )
    print(f"XCFramework: {OUTPUT}")


if __name__ == "__main__":
    main()
