#!/usr/bin/env python3
"""Validate the iOS Simulator demo app and its signed Offline Sealed payload."""

import json
import plistlib
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (
    ROOT
    / "build/ios-demo/DerivedData/Build/Products/Debug-iphonesimulator/PVMRuntimeDemo.app"
)
DELIVERY = ROOT / "build/delivery/client/ios/offline_sealed"
PROJECT = ROOT / "client/platform/ios/demo/PVMRuntimeDemo.xcodeproj/project.pbxproj"
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)


def fail(message):
    raise SystemExit(f"iOS demo check failed: {message}")


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


def main():
    info_path = APP / "Info.plist"
    executable = APP / "PVMRuntimeDemo"
    if not info_path.is_file() or not executable.is_file():
        fail(f"missing built app at {APP}")
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    if (
        info.get("CFBundleIdentifier") != "com.example.protected"
        or info.get("DTPlatformName") != "iphonesimulator"
        or info.get("MinimumOSVersion") != "15.0"
        or info.get("PVMRepositoryDemoIdentifier")
        != "com.github.kairowan.PVM-Runtime.ios-demo.v1"
    ):
        fail("bundle identity, platform, or minimum iOS version is incorrect")
    scene_manifest = info.get("UIApplicationSceneManifest", {})
    scene_configurations = scene_manifest.get("UISceneConfigurations", {}).get(
        "UIWindowSceneSessionRoleApplication", []
    )
    if (
        scene_manifest.get("UIApplicationSupportsMultipleScenes") is not False
        or len(scene_configurations) != 1
        or scene_configurations[0].get("UISceneDelegateClassName")
        != "PVMRuntimeDemo.SceneDelegate"
    ):
        fail("UIScene lifecycle is not configured for the demo")
    ipad_orientations = set(info.get("UISupportedInterfaceOrientations~ipad", []))
    if ipad_orientations != {
        "UIInterfaceOrientationPortrait",
        "UIInterfaceOrientationPortraitUpsideDown",
        "UIInterfaceOrientationLandscapeLeft",
        "UIInterfaceOrientationLandscapeRight",
    }:
        fail("iPad must support every interface orientation")
    if "arm64" not in set(run(["xcrun", "lipo", "-archs", executable]).split()):
        fail("demo executable does not contain an arm64 Simulator slice")
    run(["codesign", "--verify", "--deep", "--strict", APP])
    signature = run(["codesign", "-d", "--verbose=4", APP])
    if "Signature=adhoc" not in signature or "TeamIdentifier=not set" not in signature:
        fail("Simulator app is not locally ad-hoc signed")

    for name in ("bootstrap.json", "module-public-key.pem", "module.pvm"):
        bundled = APP / name
        generated = DELIVERY / name
        if not bundled.is_file() or not generated.is_file():
            fail(f"missing signed delivery resource {name}")
        if bundled.read_bytes() != generated.read_bytes():
            fail(f"stale or mismatched delivery resource {name}")
    bootstrap = json.loads((APP / "bootstrap.json").read_text(encoding="utf-8"))
    expected = {
        "applicationId": "com.example.protected",
        "channel": "enterprise",
        "platform": "ios",
        "profile": "offline_sealed",
        "mode": "bundled",
        "release": 5,
    }
    if any(bootstrap.get(key) != value for key, value in expected.items()):
        fail("bootstrap does not match the iOS demo runtime binding")

    privacy = APP / "PVMRuntime_PVMRuntime.bundle/PrivacyInfo.xcprivacy"
    if not privacy.is_file():
        fail("Swift Package privacy manifest is missing from the app")
    project = PROJECT.read_text(encoding="utf-8")
    if (
        "XCLocalSwiftPackageReference" not in project
        or "productName = PVMRuntime;" not in project
        or "dev-private" in project
    ):
        fail("Xcode project does not use the local PVMRuntime package safely")
    for path in APP.rglob("*"):
        if path.is_file() and any(marker in path.read_bytes() for marker in PRIVATE_KEY_MARKERS):
            fail(f"private key material found in {path.relative_to(APP)}")

    runtime = ROOT / "build/client/pvm_cli"
    run(
        [
            runtime,
            "--module",
            APP / "module.pvm",
            "--public-key",
            APP / "module-public-key.pem",
            "--app-id",
            "com.example.protected",
            "--channel",
            "enterprise",
            "--platform",
            "ios",
            "--profile",
            "offline_sealed",
            "--min-release",
            "5",
            "--validate-only",
        ]
    )
    print("iOS demo: PASS (signed Offline Sealed module, Swift Package, arm64 Simulator app)")


if __name__ == "__main__":
    main()
