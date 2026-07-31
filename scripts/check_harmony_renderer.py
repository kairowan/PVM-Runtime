#!/usr/bin/env python3
"""Run the ArkUI exact-changed regression with DevEco's bundled runtime."""

import subprocess
import shutil
from pathlib import Path

from build_harmony_artifacts import deveco_contents


ROOT = Path(__file__).resolve().parents[1]


def main():
    contents = deveco_contents()
    build = ROOT / "build/harmony-renderer-test"
    build.mkdir(parents=True, exist_ok=True)
    typescript = build / "typescript.js"
    shutil.copy2(
        contents / "tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js",
        typescript,
    )
    command = [
        shutil.which("node") or contents / "tools/node/bin/node",
        ROOT
        / "client/platform/harmony/runtime/tests/arkui_renderer_performance.mjs",
        ROOT / "client/platform/harmony/runtime/src/main/ets/pvm/ArkUiRenderer.ets",
        typescript,
        ROOT / "client/platform/harmony/runtime/src/main/ets/pvm/PvmRuntimeHost.ets",
    ]
    subprocess.run([str(value) for value in command], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
