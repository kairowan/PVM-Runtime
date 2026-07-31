#!/usr/bin/env python3
"""Run UIKit and SwiftUI commit regressions on one booted iOS Simulator."""

import argparse
import subprocess
from pathlib import Path

from run_ios_demo import booted_devices


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="booted Simulator UDID; defaults to the only booted device")
    args = parser.parse_args()
    devices = booted_devices()
    matches = (
        [device for device in devices if device["udid"] == args.device]
        if args.device
        else devices
    )
    if len(matches) != 1:
        raise SystemExit(
            "Exactly one matching booted iOS Simulator is required; "
            "boot one device or pass --device"
        )
    subprocess.run(
        [
            "xcodebuild",
            "test",
            "-scheme",
            "PVMRuntime",
            "-destination",
            f"platform=iOS Simulator,id={matches[0]['udid']}",
            "-derivedDataPath",
            ROOT / "build/ios-performance-tests",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
