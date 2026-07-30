#!/usr/bin/env python3
"""Install, exercise, and capture the PVM Runtime demo on one HarmonyOS target."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAP = Path(
    os.environ.get(
        "HARMONY_HAP",
        ROOT / "dist/harmony/PVMRuntime-demo-unsigned.hap",
    )
).expanduser().resolve()
BUNDLE_ID = "com.example.protected"
MODULE = "demo"
ABILITY = "EntryAbility"
DEMO_IDENTITY = "com.github.kairowan.PVM-Runtime.harmony-demo"
RUN_ID = f"{os.getpid()}-{time.time_ns()}"
REMOTE_LAYOUT = f"/data/local/tmp/pvm-runtime-layout-{RUN_ID}.json"
REMOTE_SCREENSHOT = f"/data/local/tmp/pvm-runtime-demo-{RUN_ID}.png"


def fail(message):
    raise SystemExit(f"HarmonyOS demo failed: {message}")


def run(command, *, check=True):
    command = [str(value) for value in command]
    print("+", shlex.join(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if check and result.returncode != 0:
        fail(f"{shlex.join(command)} exited {result.returncode}:\n{result.stdout}")
    return result


def find_hdc():
    candidates = [
        os.environ.get("HDC"),
        "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc",
        str(Path.home() / "Desktop/OpenHarmony/23/toolchains/hdc"),
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value).resolve()
    fail("hdc was not found; set HDC to the HarmonyOS SDK executable")


def connected_targets(hdc, *, physical):
    output = run([hdc, "list", "targets", "-v"]).stdout
    targets = []
    for line in output.splitlines():
        fields = line.split()
        if (
            len(fields) >= 3
            and fields[2] == "Connected"
            and (
                (physical and fields[1] == "USB")
                or (
                    not physical
                    and (
                        fields[1].lower() in ("emulator", "local")
                        or fields[0].startswith(
                            ("127.0.0.1:", "localhost:", "emulator-")
                        )
                    )
                )
            )
        ):
            targets.append(fields[0])
    return targets


def verify_signed_hap(hdc):
    sign_tool = hdc.parent / "lib/hap-sign-tool.jar"
    bundled_java = next(
        (
            parent / "jbr/Contents/Home/bin/java"
            for parent in hdc.parents
            if (parent / "jbr/Contents/Home/bin/java").is_file()
        ),
        None,
    )
    java = bundled_java or shutil.which("java")
    if not sign_tool.is_file() or java is None:
        fail("DevEco hap-sign-tool and Java are required to verify a physical-device HAP")
    with tempfile.TemporaryDirectory(prefix="pvm-hap-verify-") as directory:
        result = run(
            [
                java,
                "-jar",
                sign_tool,
                "verify-app",
                "-inFile",
                HAP,
                "-outCertChain",
                Path(directory) / "certificate.cer",
                "-outProfile",
                Path(directory) / "profile.p7b",
                "-inForm",
                "zip",
            ],
            check=False,
        )
    if result.returncode != 0:
        fail(
            "Huawei HAP signature verification failed:\n"
            + "\n".join(result.stdout.splitlines()[-8:])
        )


def validate_hap(hdc, *, physical):
    if not HAP.is_file():
        fail(f"missing {HAP}; run make harmony-packages first")
    try:
        archive = zipfile.ZipFile(HAP)
    except zipfile.BadZipFile as error:
        fail(f"invalid HAP archive: {error}")
    with archive:
        try:
            manifest = json.loads(archive.read("module.json"))
        except (KeyError, json.JSONDecodeError) as error:
            fail(f"invalid HAP module manifest: {error}")
        app = manifest.get("app", {})
        module = manifest.get("module", {})
        metadata = {
            item.get("name"): item.get("value")
            for item in module.get("metadata", [])
            if isinstance(item, dict)
        }
        if (
            app.get("bundleName") != BUNDLE_ID
            or module.get("name") != MODULE
            or metadata.get(DEMO_IDENTITY) != "v1"
        ):
            fail("HAP identity does not match this repository demo")
    if physical:
        verify_signed_hap(hdc)


def shell(hdc, target, *arguments, check=True):
    return run([hdc, "-t", target, "shell", *arguments], check=check)


def installed_demo_state(hdc, target):
    result = shell(hdc, target, "bm", "dump", "-n", BUNDLE_ID, check=False)
    output = result.stdout
    absent_markers = ("not exist", "not found", "failed to find", "error code")
    if result.returncode != 0 or any(marker in output.lower() for marker in absent_markers):
        return "absent"
    if DEMO_IDENTITY in output and BUNDLE_ID in output:
        return "repository-demo"
    if BUNDLE_ID in output:
        return "collision"
    return "absent"


def launch(hdc, target):
    shell(
        hdc,
        target,
        "aa",
        "start",
        "-a",
        ABILITY,
        "-b",
        BUNDLE_ID,
        "-m",
        MODULE,
        "-W",
    )


def walk_nodes(value):
    if isinstance(value, dict):
        attributes = value.get("attributes")
        if isinstance(attributes, dict):
            yield attributes
        for child in value.get("children", []):
            yield from walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_nodes(child)


def dump_layout(hdc, target, local_path, *, bundle=True):
    shell(hdc, target, "rm", "-f", REMOTE_LAYOUT)
    command = ["uitest", "dumpLayout", "-p", REMOTE_LAYOUT]
    if bundle:
        command.extend(["-b", BUNDLE_ID])
    result = shell(hdc, target, *command)
    if REMOTE_LAYOUT not in result.stdout:
        fail(f"layout dump did not create {REMOTE_LAYOUT}:\n{result.stdout}")
    if local_path.exists():
        local_path.unlink()
    run([hdc, "-t", target, "file", "recv", REMOTE_LAYOUT, local_path])
    shell(hdc, target, "rm", "-f", REMOTE_LAYOUT, check=False)
    return json.loads(local_path.read_text(encoding="utf-8"))


def text_values(attributes):
    return [
        str(attributes.get(name, ""))
        for name in ("text", "originalText", "description", "hint")
    ]


def wait_node(hdc, target, local_path, predicate, description, *, timeout=20):
    deadline = time.monotonic() + timeout
    last_text = []
    while time.monotonic() < deadline:
        try:
            payload = dump_layout(hdc, target, local_path)
            nodes = list(walk_nodes(payload))
            last_text = [text for node in nodes for text in text_values(node) if text]
            match = next((node for node in nodes if predicate(node)), None)
            if match is not None:
                return match
        except (json.JSONDecodeError, OSError, SystemExit):
            pass
        time.sleep(0.25)
    fail(f"timed out waiting for {description}; visible text: {last_text}")


def exact_text(value):
    return lambda attributes: value in text_values(attributes)


def bounds_center(attributes):
    match = re.fullmatch(
        r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]",
        str(attributes.get("bounds", "")),
    )
    if match is None:
        fail(f"invalid UI bounds: {attributes.get('bounds')}")
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom <= top:
        fail(f"empty UI bounds: {attributes.get('bounds')}")
    return (left + right) // 2, (top + bottom) // 2


def click_text(hdc, target, local_path, value):
    node = wait_node(hdc, target, local_path, exact_text(value), value)
    x, y = bounds_center(node)
    shell(hdc, target, "uitest", "uiInput", "click", str(x), str(y))


def seed_and_verify(hdc, target, local_path):
    wait_node(hdc, target, local_path, exact_text("Protected counter: 0"), "initial VM render")
    click_text(hdc, target, local_path, "Increment")
    wait_node(hdc, target, local_path, exact_text("Protected counter: 1"), "count 1")
    click_text(hdc, target, local_path, "Increment")
    wait_node(hdc, target, local_path, exact_text("Protected counter: 2"), "count 2")

    click_text(hdc, target, local_path, "Load async storage")
    wait_node(hdc, target, local_path, exact_text("Status: Not set"), "async storage result")

    field = wait_node(
        hdc,
        target,
        local_path,
        lambda attributes: (
            attributes.get("type") == "TextInput"
            and "Your name" in text_values(attributes)
        ),
        "name input",
    )
    x, y = bounds_center(field)
    shell(hdc, target, "uitest", "uiInput", "inputText", str(x), str(y), "Alice")
    wait_node(
        hdc,
        target,
        local_path,
        lambda attributes: "Alice" in text_values(attributes),
        "VM input state",
    )
    shell(hdc, target, "uitest", "uiInput", "keyEvent", "Back")

    shell(hdc, target, "uitest", "uiInput", "keyEvent", "Home")
    time.sleep(0.5)
    shell(hdc, target, "aa", "force-stop", BUNDLE_ID)
    launch(hdc, target)
    wait_node(hdc, target, local_path, exact_text("Protected counter: 2"), "restored count")
    wait_node(
        hdc,
        target,
        local_path,
        lambda attributes: "Alice" in text_values(attributes),
        "restored input",
    )
    wait_node(hdc, target, local_path, exact_text("Status: Not set"), "restored status")
    click_text(hdc, target, local_path, "Show host capability")
    # The system Toast is a separate overlay and is not guaranteed to appear in
    # the UITest tree; capture it visually after the contextual API returns.
    time.sleep(0.3)


def capture(hdc, target, destination):
    shell(hdc, target, "rm", "-f", REMOTE_SCREENSHOT)
    result = shell(hdc, target, "uitest", "screenCap", "-p", REMOTE_SCREENSHOT)
    if REMOTE_SCREENSHOT not in result.stdout:
        fail(f"screen capture did not create {REMOTE_SCREENSHOT}:\n{result.stdout}")
    destination = destination if destination.is_absolute() else ROOT / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{RUN_ID}.tmp")
    if temporary.exists():
        temporary.unlink()
    run([hdc, "-t", target, "file", "recv", REMOTE_SCREENSHOT, temporary])
    shell(hdc, target, "rm", "-f", REMOTE_SCREENSHOT, check=False)
    if temporary.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        temporary.unlink()
        fail(f"screen capture is not a PNG: {destination}")
    temporary.replace(destination)
    print(f"Screenshot: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        help="connected target; defaults to the only target of the selected kind",
    )
    parser.add_argument(
        "--physical",
        action="store_true",
        help="explicitly allow one USB physical device and require a signed HAP",
    )
    parser.add_argument("--reset", action="store_true", help="remove only this repository demo first")
    parser.add_argument(
        "--seed-screenshot",
        action="store_true",
        help="exercise VM count, toast, storage, input, and state restore",
    )
    parser.add_argument("--screenshot", type=Path, help="write a PNG after launch")
    args = parser.parse_args()
    if args.seed_screenshot and not args.reset:
        fail("--seed-screenshot requires --reset for deterministic state")

    hdc = find_hdc()
    validate_hap(hdc, physical=args.physical)
    targets = connected_targets(hdc, physical=args.physical)
    matches = [value for value in targets if args.target is None or value == args.target]
    if len(matches) != 1:
        fail(
            f"exactly one connected {'USB physical device' if args.physical else 'local emulator'} "
            "is required; connect one target or pass --target"
        )
    target = matches[0]
    state = installed_demo_state(hdc, target)
    if state == "collision":
        fail(f"refusing to replace unrelated emulator app {BUNDLE_ID}")
    if args.reset and state == "repository-demo":
        run([hdc, "-t", target, "uninstall", BUNDLE_ID])
        state = "absent"

    install = [hdc, "-t", target, "install"]
    if state == "repository-demo":
        install.append("-r")
    install.append(HAP)
    run(install)
    if installed_demo_state(hdc, target) != "repository-demo":
        fail("installed package identity could not be verified")
    launch(hdc, target)

    with tempfile.TemporaryDirectory(prefix="pvm-harmony-ui-") as directory:
        layout = Path(directory) / "layout.json"
        initial = (
            exact_text("Protected counter: 0")
            if args.reset or state == "absent"
            else lambda attributes: any(
                value.startswith("Protected counter: ") for value in text_values(attributes)
            )
        )
        wait_node(hdc, target, layout, initial, "PVM Runtime demo")
        if args.seed_screenshot:
            seed_and_verify(hdc, target, layout)
        if args.screenshot:
            capture(hdc, target, args.screenshot)
    kind = "physical device" if args.physical else "emulator"
    print(f"HarmonyOS {kind} demo: PASS ({target})")


if __name__ == "__main__":
    main()
