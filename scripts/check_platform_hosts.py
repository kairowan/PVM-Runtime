#!/usr/bin/env python3
"""Compile every platform host for which a local SDK/header set is available."""

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def run(command):
    subprocess.run([str(value) for value in command], cwd=str(ROOT), check=True)


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
    studio_kotlinc = Path(
        "/Applications/Android Studio.app/Contents/plugins/Kotlin/kotlinc/bin/kotlinc"
    )
    kotlinc = studio_kotlinc if studio_kotlinc.is_file() else shutil.which("kotlinc")
    if sdk is None or kotlinc is None:
        print("Android host: SKIP (SDK or kotlinc unavailable)")
        return
    platforms = sorted((sdk / "platforms").glob("android-*"))
    ndks = sorted((sdk / "ndk").iterdir())
    if not platforms or not ndks:
        print("Android host: SKIP (platform or NDK unavailable)")
        return
    sources = sorted(
        (
            ROOT
            / "client/platform/android/src/main/kotlin/com/protectedvm/host"
        ).glob("*.kt")
    )
    run(
        [
            kotlinc,
            *sources,
            "-classpath",
            platforms[-1] / "android.jar",
            "-jvm-target",
            "17",
            "-d",
            BUILD / "android-host.jar",
        ]
    )
    toolchain = ndks[-1] / "build/cmake/android.toolchain.cmake"
    output = BUILD / "android-bridge-arm64"
    run(
        [
            "cmake",
            "-S",
            ROOT / "client/platform/android",
            "-B",
            output,
            "-DCMAKE_TOOLCHAIN_FILE=" + str(toolchain),
            "-DANDROID_ABI=arm64-v8a",
            "-DANDROID_PLATFORM=24",
            "-DCMAKE_BUILD_TYPE=Release",
        ]
    )
    run(["cmake", "--build", output, "-j", "4"])
    print("Android host: PASS (Kotlin + full NDK arm64-v8a runtime)")


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
            "-warnings-as-errors",
            "-typecheck",
            *sorted((ROOT / "client/platform/ios/swift").glob("*.swift")),
        ]
    )
    print("iOS host: PASS (Objective-C++ + Swift/UIKit/SwiftUI/CryptoKit)")


def check_harmony_bridge():
    node = shutil.which("node")
    compiler = shutil.which("c++")
    if node is None or compiler is None:
        print("Harmony host: SKIP (Node-API headers unavailable)")
        return
    node_include = Path(node).resolve().parents[1] / "include" / "node"
    if not (node_include / "node_api.h").is_file():
        print("Harmony host: SKIP (Node-API headers unavailable)")
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
            "client/platform/harmony/src/main/cpp/pvm_napi.cpp",
            "-o",
            "build/pvm_napi.o",
        ]
    )
    print("Harmony host: PASS (portable Node-API C++; DevEco SDK unavailable)")


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    check_android()
    check_ios()
    check_harmony_bridge()


if __name__ == "__main__":
    main()
