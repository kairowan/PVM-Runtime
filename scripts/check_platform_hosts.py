#!/usr/bin/env python3
"""Compile every platform host for which a local SDK/header set is available."""

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def run(command, env=None):
    subprocess.run(
        [str(value) for value in command],
        cwd=str(ROOT),
        env=env,
        check=True,
    )


def find_android_sdk():
    candidates = [
        os.environ.get("ANDROID_SDK_ROOT"),
        os.environ.get("ANDROID_HOME"),
        str(Path.home() / "Library" / "Android" / "sdk"),
        str(Path.home() / "Desktop" / "android" / "sdk"),
    ]
    return next((Path(value) for value in candidates if value and Path(value).is_dir()), None)


def check_android():
    sdk = find_android_sdk()
    gradlew = ROOT / "client/platform/android/gradlew"
    if sdk is None or not gradlew.is_file():
        print("Android host: SKIP (SDK or Gradle project unavailable)")
        return
    platforms = sorted((sdk / "platforms").glob("android-*"))
    ndk_root = sdk / "ndk"
    ndks = sorted(ndk_root.iterdir()) if ndk_root.is_dir() else []
    if not platforms or not ndks:
        print("Android host: SKIP (platform or NDK unavailable)")
        return
    environment = {
        **os.environ,
        "ANDROID_HOME": str(sdk),
        "ANDROID_SDK_ROOT": str(sdk),
    }
    run(
        [
            gradlew,
            "-p",
            ROOT / "client/platform/android",
            "--no-daemon",
            ":runtime:assembleRelease",
        ],
        env=environment,
    )
    print("Android host: PASS (release AAR + Kotlin + arm64-v8a/x86_64 NDK runtime)")


def check_ios():
    if shutil.which("xcrun") is None:
        print("iOS host: SKIP (Xcode unavailable)")
        return
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True
    ).strip()
    run(
        [
            "xcrun",
            "--sdk",
            "iphonesimulator",
            "clang++",
            "-target",
            "arm64-apple-ios15.0-simulator",
            "-isysroot",
            sdk,
            "-fobjc-arc",
            "-fblocks",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-Iclient/include",
            "-Iclient/platform/ios/include",
            "-c",
            "client/platform/ios/PVMRuntimeBridge.mm",
            "-o",
            "build/PVMRuntimeBridge.o",
        ]
    )
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
            "-Iclient/platform/ios/include",
            "-swift-version",
            "6",
            "-strict-concurrency=complete",
            "-warnings-as-errors",
            "-typecheck",
            *sorted((ROOT / "client/platform/ios/swift").glob("*.swift")),
        ]
    )
    print(
        "iOS host: PASS "
        "(Objective-C++ bridge + unified Host + Swift 6/UIKit/SwiftUI/CryptoKit)"
    )


def check_harmony_bridge():
    project = ROOT / "client/platform/harmony"
    required = [
        project / "build-profile.json5",
        project / "runtime/oh-package.json5",
        project / "runtime/src/main/cpp/pvm_napi.cpp",
        project / "runtime/src/main/ets/pvm/PvmRuntimeHost.ets",
        project / "runtime/src/main/ets/pvm/PvmRuntimeTree.ets",
        project / "demo/src/main/module.json5",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        print(f"Harmony host: SKIP (DevEco project files unavailable: {', '.join(missing)})")
        return
    profile = (project / "build-profile.json5").read_text(encoding="utf-8")
    if (
        '"compileSdkVersion": "6.1.1(24)"' not in profile
        or '"compatibleSdkVersion": "6.1.0(23)"' not in profile
    ):
        raise RuntimeError("Harmony build profile must compile with API 24 and support API 23")

    sdk_candidates = [
        os.environ.get("DEVECO_SDK_HOME"),
        "/Applications/DevEco-Studio.app/Contents/sdk",
    ]
    deveco_sdk = next(
        (
            Path(value)
            for value in sdk_candidates
            if value
            and (
                (Path(value) / "default/sdk-pkg.json").is_file()
                or (Path(value) / "sdk-pkg.json").is_file()
            )
        ),
        None,
    )

    node = shutil.which("node")
    compiler = shutil.which("c++")
    if node is None or compiler is None:
        suffix = "DevEco SDK detected" if deveco_sdk else "DevEco SDK unavailable"
        print(f"Harmony portable bridge: SKIP (Node-API headers unavailable; {suffix})")
        return
    node_include = Path(node).resolve().parents[1] / "include" / "node"
    if not (node_include / "node_api.h").is_file():
        suffix = "DevEco SDK detected" if deveco_sdk else "DevEco SDK unavailable"
        print(f"Harmony portable bridge: SKIP (Node-API headers unavailable; {suffix})")
        return
    run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-DNODE_GYP_MODULE_NAME=pvm_harmony",
            "-I" + str(node_include),
            "-Iclient/include",
            "-c",
            "client/platform/harmony/runtime/src/main/cpp/pvm_napi.cpp",
            "-o",
            "build/pvm_napi.o",
        ]
    )
    sdk_status = "DevEco SDK detected" if deveco_sdk else "DevEco SDK unavailable"
    print(
        "Harmony portable bridge: PASS "
        f"(API 24/compatible API 23 project + desktop Node-API smoke; {sdk_status}; "
        "full HAR/HAP gate: make harmony-sdk-check)"
    )


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    check_android()
    check_ios()
    check_harmony_bridge()


if __name__ == "__main__":
    main()
