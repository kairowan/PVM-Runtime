#!/usr/bin/env python3
"""Check that the dependency-free project site stays GitHub-backed."""

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "index.html"
ROBOTS = ROOT / "site" / "robots.txt"
SITEMAP = ROOT / "site" / "sitemap.xml"
REPOSITORY = "https://github.com/kairowan/PVM-Runtime"
RAW = "https://raw.githubusercontent.com/kairowan/PVM-Runtime/"


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.images = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])
        elif tag == "img":
            self.images.append((values.get("src", ""), values.get("alt", "")))
        elif tag == "script":
            self.scripts += 1


def main():
    parser = SiteParser()
    source = SITE.read_text(encoding="utf-8")
    parser.feed(source)
    errors = []
    if parser.scripts:
        errors.append("site must not load JavaScript")
    invalid_links = [link for link in parser.links if not (link.startswith("#") or link.startswith(REPOSITORY))]
    if invalid_links:
        errors.append("links must point to GitHub: " + ", ".join(invalid_links))
    for src, alt in parser.images:
        if not src.startswith(RAW):
            errors.append("image must be served by the repository on GitHub: " + src)
        if not alt.strip():
            errors.append("image is missing alt text: " + src)
    for required in ("/releases/latest", "/discussions", "/issues/new/choose", "/tree/main/docs"):
        if not any(link == REPOSITORY + required for link in parser.links):
            errors.append("missing GitHub entry point: " + required)
    if 'href="http://' in source or 'src="http://' in source:
        errors.append("site contains an insecure HTTP URL")
    if "Sitemap: https://kairowan.github.io/PVM-Runtime/sitemap.xml" not in ROBOTS.read_text(encoding="utf-8"):
        errors.append("robots.txt does not advertise the GitHub Pages sitemap")
    if "<loc>https://kairowan.github.io/PVM-Runtime/</loc>" not in SITEMAP.read_text(encoding="utf-8"):
        errors.append("sitemap.xml does not contain the canonical page")
    if errors:
        print("\n".join(errors))
        return 1
    print("Website: PASS (%d GitHub links, %d repository images, no JavaScript)" % (len(parser.links), len(parser.images)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
