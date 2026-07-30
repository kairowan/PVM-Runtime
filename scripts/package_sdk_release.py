#!/usr/bin/env python3
"""Package precompiled Android, iOS, and HarmonyOS SDK release assets."""

import argparse
import gzip
import hashlib
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
OUTPUT = DIST / "release"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def fail(message):
    raise SystemExit(f"SDK release packaging failed: {message}")


def add_zip_tree(archive, source, prefix):
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        relative = Path(prefix) / path.relative_to(source)
        info = zipfile.ZipInfo(relative.as_posix(), FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (path.stat().st_mode & 0xFFFF) << 16
        archive.writestr(info, path.read_bytes())


def create_zip(destination, sources):
    with zipfile.ZipFile(destination, "w") as archive:
        for source, prefix in sources:
            add_zip_tree(archive, source, prefix)


def normalized_tar(info):
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def create_tar(destination, source, prefix):
    with destination.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                archive.add(
                    source,
                    arcname=prefix,
                    recursive=True,
                    filter=normalized_tar,
                )


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def binary_package_manifest():
    return """// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "PVMRuntimeBinary",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "PVMRuntime", targets: ["PVMRuntime"]),
    ],
    targets: [
        .binaryTarget(name: "PVMRuntime", path: "PVMRuntime.xcframework"),
    ]
)
"""


def require(path):
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}; run the matching platform gate")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.5.0")
    args = parser.parse_args()
    version = args.version
    if not version or any(character not in "0123456789." for character in version):
        fail("version must contain only digits and dots")

    android_aar = require(DIST / f"android/pvm-runtime-{version}.aar")
    android_maven = require(DIST / "android/maven")
    ios_framework = require(DIST / "ios/PVMRuntime.xcframework")
    harmony_har = require(DIST / f"harmony/pvm-runtime-{version}.har")

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    android_asset = OUTPUT / f"pvm-runtime-android-{version}.aar"
    harmony_asset = OUTPUT / f"pvm-runtime-harmony-{version}.har"
    shutil.copy2(android_aar, android_asset)
    shutil.copy2(harmony_har, harmony_asset)
    shutil.copy2(ROOT / "LICENSE", OUTPUT / "LICENSE")

    maven_asset = OUTPUT / f"pvm-runtime-android-maven-{version}.tgz"
    create_tar(maven_asset, android_maven, "maven")

    xcframework_asset = OUTPUT / f"PVMRuntime-{version}.xcframework.zip"
    create_zip(
        xcframework_asset,
        [(ios_framework, "PVMRuntime.xcframework")],
    )

    with tempfile.TemporaryDirectory(prefix="pvm-binary-package-") as name:
        package = Path(name) / "PVMRuntimeBinaryPackage"
        package.mkdir()
        (package / "Package.swift").write_text(
            binary_package_manifest(),
            encoding="utf-8",
        )
        shutil.copy2(ROOT / "LICENSE", package / "LICENSE")
        shutil.copytree(ios_framework, package / "PVMRuntime.xcframework")
        binary_package_asset = OUTPUT / f"PVMRuntimeBinaryPackage-{version}.zip"
        create_zip(binary_package_asset, [(package, package.name)])

    assets = sorted(
        path for path in OUTPUT.iterdir() if path.name != "SHA256SUMS"
    )
    checksums = OUTPUT / "SHA256SUMS"
    checksums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in assets),
        encoding="utf-8",
    )

    with zipfile.ZipFile(binary_package_asset) as archive:
        names = set(archive.namelist())
    if (
        "PVMRuntimeBinaryPackage/Package.swift" not in names
        or "PVMRuntimeBinaryPackage/LICENSE" not in names
        or not any(
            name.endswith("/PVMRuntime.framework/PVMRuntime") for name in names
        )
    ):
        fail("binary Swift Package is incomplete")
    with tarfile.open(maven_asset, "r:gz") as archive:
        if not any(member.name.endswith(".pom") for member in archive.getmembers()):
            fail("Android Maven archive does not contain a POM")
    if len(checksums.read_text(encoding="utf-8").splitlines()) != len(assets):
        fail("checksum inventory is incomplete")

    for path in (*assets, checksums):
        print(f"Release asset: {path}")


if __name__ == "__main__":
    main()
