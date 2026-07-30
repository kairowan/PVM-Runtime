#!/usr/bin/env python3
"""Install the pinned Qt SDK inside this repository for Migration Studio."""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build" / "migration-studio-tools"
PYTHON_PACKAGES = TOOLS / "python"
QT_ROOT = ROOT / "third_party" / "qt"
QT_LICENSES = QT_ROOT / "licenses"
PREFIX_FILE = TOOLS / "qt-prefix.txt"
AQT_VERSION = "3.3.0"
DEFAULT_QT_VERSION = "6.12.0"
QT_LICENSE_REF = "617242bba272518b57f7c201d63af299abcb877b"
LICENSE_URLS = {
    "GPL-3.0-only.txt": (
        f"https://raw.githubusercontent.com/qt/qtbase/{QT_LICENSE_REF}/"
        "LICENSES/GPL-3.0-only.txt"
    ),
    "LGPL-3.0-only.txt": (
        f"https://raw.githubusercontent.com/qt/qtbase/{QT_LICENSE_REF}/"
        "LICENSES/LGPL-3.0-only.txt"
    ),
}


def target():
    system = platform.system()
    if system == "Darwin":
        return "mac", "clang_64"
    if system == "Linux":
        return "linux", "linux_gcc_64"
    if system == "Windows":
        return "windows", "win64_msvc2022_64"
    raise SystemExit(f"unsupported desktop host: {system}")


def qt_prefix(version):
    candidates = sorted(
        QT_ROOT.glob(f"{version}/**/lib/cmake/Qt6/Qt6Config.cmake")
    )
    return candidates[0].parents[3] if candidates else None


def ensure_aqt():
    if (PYTHON_PACKAGES / "aqt").is_dir():
        return
    PYTHON_PACKAGES.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--target",
            str(PYTHON_PACKAGES),
            f"aqtinstall=={AQT_VERSION}",
        ],
        cwd=ROOT,
        check=True,
    )


def install(version):
    prefix = qt_prefix(version)
    if prefix is not None:
        return prefix
    ensure_aqt()
    host, architecture = target()
    archives = TOOLS / "archives"
    archives.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PYTHON_PACKAGES)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "aqt",
            "install-qt",
            host,
            "desktop",
            version,
            architecture,
            "--outputdir",
            str(QT_ROOT),
            "--archive-dest",
            str(archives),
            "--internal",
            "--archives",
            "qtbase",
        ],
        cwd=TOOLS,
        env=environment,
        check=True,
    )
    prefix = qt_prefix(version)
    if prefix is None:
        raise SystemExit("Qt installation completed without Qt6Config.cmake")
    return prefix


def ensure_licenses():
    QT_LICENSES.mkdir(parents=True, exist_ok=True)
    for name, url in LICENSE_URLS.items():
        target_path = QT_LICENSES / name
        if target_path.is_file():
            continue
        temporary = target_path.with_suffix(target_path.suffix + ".tmp")
        curl = shutil.which("curl")
        if curl:
            subprocess.run(
                [
                    curl,
                    "--http1.1",
                    "--fail",
                    "--location",
                    "--retry",
                    "3",
                    "--retry-all-errors",
                    "--retry-delay",
                    "1",
                    "--connect-timeout",
                    "10",
                    "--max-time",
                    "60",
                    url,
                    "--output",
                    str(temporary),
                ],
                check=True,
            )
            encoded = temporary.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=30) as response:
                encoded = response.read()
            temporary.write_bytes(encoded)
        if b"GENERAL PUBLIC LICENSE" not in encoded:
            temporary.unlink(missing_ok=True)
            raise SystemExit(f"unexpected Qt license response: {url}")
        os.replace(temporary, target_path)
    (QT_LICENSES / "NOTICE.txt").write_text(
        "PVM Migration Studio dynamically links Qt 6.12.0.\n"
        "Qt is copyright The Qt Company Ltd. and other contributors and is "
        "available under commercial and open-source license terms.\n"
        "This development package uses the LGPL-3.0-only option. See the "
        "accompanying GPL-3.0-only.txt and LGPL-3.0-only.txt files and "
        "https://www.qt.io/licensing/.\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=os.environ.get("PVM_QT_VERSION", DEFAULT_QT_VERSION),
    )
    args = parser.parse_args()
    prefix = install(args.version).resolve()
    ensure_licenses()
    TOOLS.mkdir(parents=True, exist_ok=True)
    PREFIX_FILE.write_text(str(prefix) + "\n", encoding="utf-8")
    print(prefix)


if __name__ == "__main__":
    main()
