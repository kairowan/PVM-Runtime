#!/usr/bin/env python3
"""Validate local documentation links and visual assets without extra dependencies."""

import re
import struct
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
HTML_SOURCE = re.compile(r"\bsrc=['\"]([^'\"]+)['\"]")


def main():
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    errors = []
    for document in documents:
        source = document.read_text(encoding="utf-8")
        for target in [*MARKDOWN_LINK.findall(source), *HTML_SOURCE.findall(source)]:
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = urllib.parse.unquote(target.split("#", 1)[0])
            if path_text and not (document.parent / path_text).resolve().exists():
                errors.append("%s: missing local link %s" % (document.relative_to(ROOT), target))
    for asset in sorted((ROOT / "docs" / "assets").glob("*.svg")):
        try:
            ET.parse(asset)
        except ET.ParseError as error:
            errors.append("%s: invalid SVG: %s" % (asset.relative_to(ROOT), error))
    for asset in sorted((ROOT / "docs" / "assets").glob("*.png")):
        encoded = asset.read_bytes()
        if len(encoded) < 24 or encoded[:8] != b"\x89PNG\r\n\x1a\n":
            errors.append("%s: invalid PNG header" % asset.relative_to(ROOT))
            continue
        width, height = struct.unpack(">II", encoded[16:24])
        if width == 0 or height == 0:
            errors.append("%s: invalid PNG dimensions" % asset.relative_to(ROOT))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Documentation: PASS (%d Markdown files, %d visual assets)" % (
        len(documents), len(list((ROOT / "docs" / "assets").glob("*.*")))
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
