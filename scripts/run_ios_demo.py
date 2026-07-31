#!/usr/bin/env python3
"""Install and launch the PVM Runtime demo on one booted iOS Simulator."""

import argparse
import json
import plistlib
import shlex
import subprocess
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (
    ROOT
    / "build/ios-demo/DerivedData/Build/Products/Debug-iphonesimulator/PVMRuntimeDemo.app"
)
BUNDLE_ID = "com.example.protected"
DEMO_IDENTITY = "com.github.kairowan.PVM-Runtime.ios-demo.v1"
SCREENSHOT_MARKER = Path("Library/Caches/pvm-screenshot-ready")
RESTORED_STATE_MARKER = Path("Library/Caches/pvm-state-restored")
STATE_FILE = Path("Library/Application Support/counter.state")


def run(command):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout


def booted_devices():
    payload = json.loads(run(["xcrun", "simctl", "list", "devices", "booted", "--json"]))
    return [
        device
        for runtime, devices in payload.get("devices", {}).items()
        if "SimRuntime.iOS-" in runtime
        for device in devices
        if device.get("state") == "Booted" and device.get("isAvailable", True)
    ]


def app_container(device, kind, *, allow_missing=False):
    command = ["xcrun", "simctl", "get_app_container", device, BUNDLE_ID, kind]
    print("+", shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = result.stdout.strip()
    if result.returncode == 0:
        return Path(output)
    if allow_missing and result.returncode == 2:
        return None
    raise SystemExit(output or f"simctl get_app_container failed with {result.returncode}")


def require_repository_demo(app, description):
    try:
        with (app / "Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as error:
        raise SystemExit(f"Refusing to replace {description}: unreadable Info.plist ({error})")
    if (
        info.get("CFBundleIdentifier") != BUNDLE_ID
        or info.get("CFBundleExecutable") != "PVMRuntimeDemo"
        or info.get("PVMRepositoryDemoIdentifier") != DEMO_IDENTITY
    ):
        raise SystemExit(
            f"Refusing to replace {description}: {BUNDLE_ID} is not this repository demo"
        )


def wait_for_token(path, token, description):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if path.read_text(encoding="utf-8") == token:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise SystemExit(f"Timed out waiting for {description}")


def wait_for_state(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if path.stat().st_size > 0:
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise SystemExit("Timed out waiting for sceneDidEnterBackground state persistence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="booted Simulator UDID; defaults to the only booted device")
    parser.add_argument("--reset", action="store_true", help="uninstall only this demo before install")
    parser.add_argument(
        "--seed-screenshot",
        action="store_true",
        help="drive VM events to count=2, Status=Not set, and Alice",
    )
    parser.add_argument(
        "--verify-state-restore",
        action="store_true",
        help="background, terminate, relaunch, and verify VM state restoration",
    )
    parser.add_argument("--screenshot", type=Path, help="write a PNG after launch")
    args = parser.parse_args()
    if args.verify_state_restore and not args.reset:
        parser.error("--verify-state-restore requires --reset")

    devices = booted_devices()
    if args.device:
        matches = [device for device in devices if device["udid"] == args.device]
    else:
        matches = devices
    if len(matches) != 1:
        raise SystemExit(
            "Exactly one matching booted iOS Simulator is required; "
            "boot one device or pass --device"
        )
    device = matches[0]
    if not APP.is_dir():
        raise SystemExit(f"Missing demo app: run make ios-demo-check first ({APP})")
    require_repository_demo(APP, "built app")

    installed = app_container(device["udid"], "app", allow_missing=True)
    if installed is not None:
        require_repository_demo(installed, "installed Simulator app")
        if args.reset:
            run(["xcrun", "simctl", "uninstall", device["udid"], BUNDLE_ID])
    run(["xcrun", "simctl", "install", device["udid"], APP])
    require_repository_demo(
        app_container(device["udid"], "app"),
        "newly installed Simulator app",
    )
    data = app_container(device["udid"], "data")
    command = [
        "xcrun",
        "simctl",
        "launch",
        "--terminate-running-process",
        device["udid"],
        BUNDLE_ID,
    ]
    screenshot_token = None
    if args.seed_screenshot or args.verify_state_restore:
        screenshot_token = uuid.uuid4().hex
        command.extend(["-PVMSeedScreenshotToken", screenshot_token])
    launch = run(command).strip()

    if screenshot_token:
        wait_for_token(data / SCREENSHOT_MARKER, screenshot_token, "VM-rendered seed state")
    if args.verify_state_restore:
        run(
            [
                "xcrun",
                "simctl",
                "launch",
                "--terminate-running-process",
                device["udid"],
                "com.apple.mobilesafari",
            ]
        )
        wait_for_state(data / STATE_FILE)
        run(["xcrun", "simctl", "terminate", device["udid"], BUNDLE_ID])
        restored_token = uuid.uuid4().hex
        launch = run(
            [
                "xcrun",
                "simctl",
                "launch",
                device["udid"],
                BUNDLE_ID,
                "-PVMVerifyRestoredStateToken",
                restored_token,
            ]
        ).strip()
        wait_for_token(
            data / RESTORED_STATE_MARKER,
            restored_token,
            "restored VM-rendered state",
        )
        print("State restore: PASS (background persistence, termination, relaunch)")
    elif not screenshot_token:
        time.sleep(1)

    if args.screenshot:
        destination = args.screenshot
        if not destination.is_absolute():
            destination = ROOT / destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(["xcrun", "simctl", "io", device["udid"], "screenshot", "--type=png", destination])
        print(f"Screenshot: {destination}")
    print(f"Running on {device['name']} ({device['udid']}): {launch}")


if __name__ == "__main__":
    main()
