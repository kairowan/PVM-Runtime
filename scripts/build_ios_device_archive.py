#!/usr/bin/env python3
"""Build and verify a manually signed iOS device archive from explicit release inputs."""

import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "client/platform/ios/demo/PVMRuntimeDemo.xcodeproj"
ARCHIVE = ROOT / "dist/ios/PVMRuntimeDemo.xcarchive"


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit("missing required release input: %s" % name)
    return value


def main():
    team = required("PVM_IOS_TEAM_ID")
    identity = required("PVM_IOS_SIGNING_IDENTITY")
    profile = required("PVM_IOS_PROVISIONING_PROFILE")
    bundle = os.environ.get("PVM_IOS_BUNDLE_ID", "com.example.protected").strip()
    if re.fullmatch(r"[A-Za-z0-9.-]+", bundle) is None:
        raise SystemExit("PVM_IOS_BUNDLE_ID contains unsafe characters")
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "xcodebuild",
            "-quiet",
            "-project",
            str(PROJECT),
            "-scheme",
            "PVMRuntimeDemo",
            "-configuration",
            "Release",
            "-destination",
            "generic/platform=iOS",
            "-archivePath",
            str(ARCHIVE),
            "archive",
            "CODE_SIGN_STYLE=Manual",
            "DEVELOPMENT_TEAM=" + team,
            "CODE_SIGN_IDENTITY=" + identity,
            "PROVISIONING_PROFILE_SPECIFIER=" + profile,
            "PRODUCT_BUNDLE_IDENTIFIER=" + bundle,
        ],
        cwd=ROOT,
        check=True,
    )
    applications = list((ARCHIVE / "Products/Applications").glob("*.app"))
    if len(applications) != 1 or not (applications[0] / "embedded.mobileprovision").is_file():
        raise SystemExit("archive does not contain exactly one provisioned application")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", "--verbose=2", applications[0]],
        check=True,
    )
    print("iOS device archive: %s" % ARCHIVE)


if __name__ == "__main__":
    main()
