#!/usr/bin/env python3
"""check_readme.py — README headings, docs links, and measured numbers.

Fails when README.md is missing a required heading, links a docs/*.md file that
is not in the tree, or states a measurement that scripts/check_numbers.py would
reject against docs/NUMBERS.md.

Headings and links inside fenced code blocks do not count.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED_HEADINGS = (
    "Problem & why a graph",
    "Architecture diagram",
    "Graph data model",
    "Cypher & algorithms",
    "Interfaces",
    "Tracks entered",
    "Evaluation",
    "Security model",
    "Limitations",
    "AI disclosure",
    "License",
)

FENCE = re.compile(r"```.*?```", re.S)
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
DOCS_MD = re.compile(r"(?:^|/)docs/.+\.md$", re.I)


def _visible(text: str) -> str:
    return FENCE.sub("\n", text)


def missing_headings(text: str) -> list[str]:
    found = {m.group(1).strip() for m in HEADING.finditer(_visible(text))}
    return [title for title in REQUIRED_HEADINGS if title not in found]


def dead_doc_links(text: str, root: Path) -> list[str]:
    problems: list[str] = []
    visible = _visible(text)
    for match in LINK.finditer(visible):
        raw = match.group(1).strip("<>")
        if raw.startswith(("http://", "https://", "mailto:")):
            continue
        path = raw.split("#", 1)[0].split("?", 1)[0]
        if not path or not DOCS_MD.search(path.replace("\\", "/")):
            continue
        relative = path[2:] if path.startswith("./") else path
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            problems.append(f"docs link escapes the repo: {raw}")
            continue
        if not target.is_file():
            line_no = visible.count("\n", 0, match.start()) + 1
            problems.append(f"README.md:{line_no}: missing {relative}")
    return problems


def number_problems(readme: Path, numbers: Path) -> list[str]:
    scripts = Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from check_numbers import parse_numbers_block, scan_file

    if not numbers.is_file():
        return [f"missing numbers file: {numbers}"]
    allowed = parse_numbers_block(numbers)
    return scan_file(readme, allowed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="check README headings, docs links, and numbers")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--numbers", default="docs/NUMBERS.md")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    readme = root / args.readme
    if not readme.is_file():
        print(f"[check-readme] FAIL: {readme} missing")
        return 1
    text = readme.read_text(encoding="utf-8")
    problems = [f"missing heading: {title}" for title in missing_headings(text)]
    problems += dead_doc_links(text, root)
    problems += number_problems(readme, root / args.numbers)
    if problems:
        print("[check-readme] FAIL:")
        for item in problems:
            print("  " + item)
        return 1
    print(
        "[check-readme] PASS: "
        f"{len(REQUIRED_HEADINGS)} headings, docs/*.md links, numbers"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
