#!/usr/bin/env python3
"""Validate local Markdown links and repository SVG assets without extra dependencies."""

import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")


def main():
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    errors = []
    for document in documents:
        source = document.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(source):
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
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Documentation: PASS (%d Markdown files, %d SVG assets)" % (
        len(documents), len(list((ROOT / "docs" / "assets").glob("*.svg")))
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
