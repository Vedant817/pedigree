#!/usr/bin/env python3
"""check_numbers.py - every measurement in README/blog must come from docs/NUMBERS.md.

Rules (deliberately mechanical and conservative):
- Text outside code spans/fences is scanned for numeric tokens.
- A token is a CLAIM when it has a unit suffix (% ms s x k MB GB KB nodes edges bytes
  req/s) or is a >=3-digit number or contains a decimal point. Claims must appear in
  the `<!-- NUMBERS:BEGIN --> ... <!-- NUMBERS:END -->` block of docs/NUMBERS.md.
- Bare 1-2 digit integers and years are structural (dates, "2 tracks") and exempt.
- Identifiers that embed digits (F-01, AT0.1, docs/02, S1, 127.0.0.1) are exempt.

Usage: python scripts/check_numbers.py [files...]
       (default: README.md, docs/BLOG.md, docs/BLOG-DRAFT.md, docs/DEMO_SCRIPT.md)
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BEGIN = "<!-- NUMBERS:BEGIN -->"
END = "<!-- NUMBERS:END -->"
DEFAULT_TARGETS = [
    "README.md",
    "docs/BLOG.md",
    "docs/BLOG-DRAFT.md",
    "docs/DEMO_SCRIPT.md",
]

NUM_TOKEN = re.compile(r"(?<![A-Za-z0-9_./#@-])(\d[\d,]*(?:\.\d+)?)(?![\w])")
UNIT = re.compile(r"\s*(%|ms\b|s\b|x\b|k\b|KB\b|MB\b|GB\b|nodes\b|edges\b|bytes\b|req/s\b)")
FENCE = re.compile(r"```.*?```", re.S)
INLINE = re.compile(r"`[^`]*`")
STRUCTURAL = (
    re.compile(r"^(?:19|20)\d\d$"),  # years
    re.compile(r"^\d{1,2}$"),  # bare small prose counts ("2 tracks")
    re.compile(r"^127\.0\.0\.1$"),
)


def parse_numbers_block(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"[check-numbers] {path} lacks {BEGIN} / {END} markers")
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    allowed: set[str] = set()
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        for token in NUM_TOKEN.finditer(line.split("=", 1)[1]):
            allowed.add(token.group(1).replace(",", ""))
    return allowed


def scan_file(path: Path, allowed: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = FENCE.sub(" ", text)
    text = INLINE.sub(" ", text)
    problems: list[str] = []
    for m in NUM_TOKEN.finditer(text):
        token = m.group(1).replace(",", "")
        unit = UNIT.match(text[m.end():])
        if unit:  # a measurement with a unit is always a claim
            if token not in allowed:
                line_no = text.count("\n", 0, m.start()) + 1
                problems.append(
                    f"{path}:{line_no}: '{m.group(0)}{unit.group(0)}' not in docs/NUMBERS.md"
                )
            continue
        if token in allowed:
            continue
        if any(rx.match(token) for rx in STRUCTURAL):  # years, ports, bare small counts
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        problems.append(f"{path}:{line_no}: '{m.group(0)}' not in docs/NUMBERS.md")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="check README/blog numbers against docs/NUMBERS.md")
    ap.add_argument("files", nargs="*", default=None)
    ap.add_argument("--numbers", default="docs/NUMBERS.md")
    args = ap.parse_args(argv)
    root = Path.cwd()
    numbers_file = root / args.numbers
    if not numbers_file.exists():
        print(f"[check-numbers] FAIL: {numbers_file} missing")
        return 1
    allowed = parse_numbers_block(numbers_file)
    targets = args.files or [t for t in DEFAULT_TARGETS if (root / t).exists()]
    if not targets:
        print("[check-numbers] no target files present; nothing to check")
        return 0
    problems: list[str] = []
    for t in targets:
        p = root / t
        if not p.exists():
            print(f"[check-numbers] skip (missing): {t}")
            continue
        problems += scan_file(p, allowed)
    if problems:
        print("[check-numbers] FAIL:")
        for p in problems:
            print("  " + p)
        print("  -> add the value to docs/NUMBERS.md (with its source) or fix the text")
        return 1
    allowed_n = len(allowed)
    print(f"[check-numbers] PASS: {len(targets)} file(s) checked against {allowed_n} allowed values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
