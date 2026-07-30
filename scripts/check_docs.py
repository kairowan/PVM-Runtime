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
EXCLUDED_PARTS = {
    ".git",
    ".gradle",
    ".idea",
    "build",
    "dist",
    "third_party",
}


def markdown_documents():
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def language_peer(document):
    suffix = ".zh-CN.md"
    if document.name.endswith(suffix):
        return document.with_name(document.name[: -len(suffix)] + ".md")
    return document.with_name(document.stem + suffix)


def main():
    documents = markdown_documents()
    errors = []
    for document in documents:
        source = document.read_text(encoding="utf-8")
        targets = [*MARKDOWN_LINK.findall(source), *HTML_SOURCE.findall(source)]
        peer = language_peer(document)
        if not peer.is_file():
            errors.append(
                "%s: missing language peer %s"
                % (document.relative_to(ROOT), peer.relative_to(ROOT))
            )
        elif not any(
            not target.startswith(("http://", "https://", "mailto:", "#"))
            and (
                document.parent
                / urllib.parse.unquote(target.split("#", 1)[0])
            ).resolve()
            == peer.resolve()
            for target in targets
        ):
            errors.append(
                "%s: missing language switch link to %s"
                % (document.relative_to(ROOT), peer.name)
            )
        for target in targets:
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
    print(
        "Documentation: PASS (%d bilingual Markdown files, %d visual assets)"
        % (
            len(documents),
            len(list((ROOT / "docs" / "assets").glob("*.*"))),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
