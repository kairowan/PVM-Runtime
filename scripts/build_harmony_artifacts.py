#!/usr/bin/env python3
"""Build HarmonyOS artifacts or prepare a clean DevEco signing workspace."""

import argparse
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "client" / "platform" / "harmony"
DELIVERY = ROOT / "build" / "delivery" / "client" / "harmonyos" / "offline_sealed"
DIST = ROOT / "dist" / "harmony"
HAR = DIST / "pvm-runtime-0.5.0.har"
HAP = DIST / "PVMRuntime-demo-unsigned.hap"
DELIVERY_FILES = ("bootstrap.json", "module-public-key.pem", "module.pvm")


def fail(message):
    raise SystemExit(f"HarmonyOS artifact build failed: {message}")


def run(command, *, cwd, env):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def deveco_contents():
    configured = os.environ.get("DEVECO_STUDIO_HOME")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path("/Applications/DevEco-Studio.app"),
        Path.home() / "Applications" / "DevEco-Studio.app",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        contents = candidate / "Contents" if candidate.suffix == ".app" else candidate
        if (
            (contents / "tools/node/bin/node").is_file()
            and (contents / "tools/hvigor/hvigor/bin/hvigor.js").is_file()
            and (contents / "tools/ohpm/bin/ohpm").is_file()
            and (contents / "sdk/default").is_dir()
        ):
            return contents.resolve()
    fail("DevEco Studio was not found; set DEVECO_STUDIO_HOME")


def copy_project(destination):
    client = destination / "client"
    client.mkdir(parents=True)
    shutil.copy2(ROOT / "client/CMakeLists.txt", client / "CMakeLists.txt")
    shutil.copytree(ROOT / "client/include", client / "include")
    shutil.copytree(ROOT / "client/src", client / "src")
    shutil.copytree(
        SOURCE,
        client / "platform/harmony",
        ignore=shutil.ignore_patterns(
            ".hvigor",
            ".cxx",
            "build",
            "local.properties",
            "oh_modules",
        ),
    )
    cmake = client / "platform/harmony/runtime/src/main/cpp/CMakeLists.txt"
    contents = cmake.read_text(encoding="utf-8")
    marker = "project(pvm_harmony_bridge LANGUAGES CXX)\n"
    if marker not in contents:
        fail("HarmonyOS CMake project marker was not found")
    mappings = "\n".join(
        f"add_compile_options(-f{kind}-prefix-map={path}=.)"
        for kind in ("file", "debug", "macro")
        for path in dict.fromkeys((str(destination), str(destination.resolve())))
    )
    cmake.write_text(
        contents.replace(marker, f"{marker}\n{mappings}\n", 1),
        encoding="utf-8",
    )
    rawfiles = client / "platform/harmony/demo/src/main/resources/rawfile"
    rawfiles.mkdir(parents=True, exist_ok=True)
    for name in DELIVERY_FILES:
        source = DELIVERY / name
        if not source.is_file():
            fail(f"delivery input is missing: {source}; run `make delivery-matrix`")
        shutil.copy2(source, rawfiles / name)
    return client / "platform/harmony"


def hvigor_environment(contents, temporary):
    node_path = temporary / "node-path/@ohos"
    node_path.mkdir(parents=True)
    for package in ("hvigor", "hvigor-ohos-plugin"):
        os.symlink(contents / f"tools/hvigor/{package}", node_path / package)

    return {
        **os.environ,
        "DEVECO_SDK_HOME": str(contents / "sdk"),
        "NODE_PATH": str(node_path.parent),
        "ZERO_AR_DATE": "1",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-project",
        type=Path,
        metavar="DIRECTORY",
        help="copy the project and delivery inputs to an empty DevEco-safe directory",
    )
    args = parser.parse_args()
    if not SOURCE.is_dir():
        fail(f"project is missing: {SOURCE}")
    if args.prepare_project is not None:
        destination = args.prepare_project.expanduser().resolve()
        if not all(
            character.isascii()
            and (character.isalnum() or character in "/._-")
            for character in str(destination)
        ):
            fail("prepared project path must use ASCII letters, digits, '/', '.', '_' or '-'")
        if destination.exists() and (
            not destination.is_dir() or any(destination.iterdir())
        ):
            fail(f"prepared project directory must be empty: {destination}")
        project = copy_project(destination)
        print(f"Prepared DevEco signing project: {project}")
        print("Configure a Huawei signing profile only in this disposable copy.")
        return
    contents = deveco_contents()
    node = contents / "tools/node/bin/node"
    hvigor = contents / "tools/hvigor/hvigor/bin/hvigor.js"
    ohpm = contents / "tools/ohpm/bin/ohpm"

    with tempfile.TemporaryDirectory(prefix="pvm-harmony-build-", dir="/tmp") as name:
        temporary = Path(name)
        # ponytail: DevEco rejects '+' in project paths. A disposable ASCII path
        # is the smallest reliable boundary; its CMake prefix maps avoid leaks.
        project = copy_project(temporary)
        env = hvigor_environment(contents, temporary)
        run([ohpm, "install", "--all", "--lockfile_stable_order"], cwd=project, env=env)

        common = [
            node,
            hvigor,
            "--mode",
            "module",
            "-p",
            "product=default",
            "-p",
            "buildMode=release",
            "-p",
            "requiredDeviceType=phone",
        ]
        run(
            [*common, "-p", "module=runtime@default", "assembleHar", "--no-daemon"],
            cwd=project,
            env=env,
        )
        run(
            [*common, "-p", "module=demo@default", "assembleHap", "--no-daemon"],
            cwd=project,
            env=env,
        )

        built_har = project / "runtime/build/default/outputs/default/runtime.har"
        built_hap = (
            project / "demo/build/default/outputs/default/demo-default-unsigned.hap"
        )
        if not built_har.is_file() or not built_hap.is_file():
            fail("DevEco completed without producing the expected HAR/HAP")
        DIST.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_har, HAR)
        shutil.copy2(built_hap, HAP)

    print(f"HAR: {HAR}")
    print(f"Unsigned emulator HAP: {HAP}")
    print("Physical devices and AppGallery builds require your Huawei signing profile.")


if __name__ == "__main__":
    main()
