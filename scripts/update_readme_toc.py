#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Update the README table of contents from Markdown ATX headings (## … ######)."""
from __future__ import annotations

import argparse
import html
from pathlib import Path
import re
import sys

START = "<!-- toc:start -->"
END = "<!-- toc:end -->"
DEFAULT_README = Path(__file__).resolve().parents[1] / "Readme.md"


def heading_text(source: str) -> str:
    source = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", source)
    source = re.sub(r"<[^>]+>", "", source)
    source = source.replace("`", "").replace("*", "").replace("~", "")
    source = re.sub(r"(?<!\w)_+|_+(?!\w)", "", source)
    return html.unescape(source).strip()


def table_of_contents(document: str) -> str:
    entries = []
    occurrences: dict[str, int] = {}
    in_toc = False
    fence_char, fence_length = "", 0
    # Comments cannot introduce headings; retain the two control markers.
    document = re.sub(r"<!--.*?-->", lambda m: m[0] if m[0] in (START, END) else "", document, flags=re.DOTALL)
    for line in document.splitlines():
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_char:
            if fence and fence[1][0] == fence_char and len(fence[1]) >= fence_length and not fence[2].strip():
                fence_char, fence_length = "", 0
            continue
        if fence:
            fence_char, fence_length = fence[1][0], len(fence[1])
            continue
        if line.strip() == START:
            in_toc = True
            continue
        if line.strip() == END:
            in_toc = False
            continue
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match[1])
        title = heading_text(re.sub(r"[ \t]+#+[ \t]*$", "", match[2]))
        slug = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        original = slug
        while slug in occurrences:
            occurrences[original] += 1
            slug = f"{original}-{occurrences[original]}"
        occurrences[slug] = 0
        if not in_toc and level >= 2 and title:
            label = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            entries.append(f"{'  ' * (level - 2)}- [{label}](#{slug})")
    return "\n".join(entries)


def update_document(document: str) -> str:
    if document.count(START) != 1 or document.count(END) != 1:
        raise ValueError(f"README must contain exactly one {START} / {END} pair")
    start, end = document.index(START) + len(START), document.index(END)
    if start > end:
        raise ValueError("TOC markers are in the wrong order")
    newline = "\r\n" if "\r\n" in document else "\n"
    prefix, suffix = document[:start], document[end:]
    # Seed the generated heading before slugging, so collisions stay correct.
    skeleton = prefix + newline + "## Оглавление" + newline + suffix
    toc = table_of_contents(skeleton).replace("\n", newline)
    return prefix + newline*2 + "## Оглавление" + newline*2 + toc + newline*2 + suffix


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_README)
    parser.add_argument("--check", action="store_true", help="Exit 1 if the TOC is stale; do not modify files")
    args = parser.parse_args(argv)
    try:
        with args.path.open(encoding="utf-8", newline="") as stream:
            current = stream.read()
        updated = update_document(current)
        if updated == current:
            print("README table of contents is up to date.")
            return 0
        if args.check:
            print("README table of contents is stale. Run: python3 scripts/update_readme_toc.py", file=sys.stderr)
            return 1
        with args.path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
        print(f"Updated table of contents: {args.path}")
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
