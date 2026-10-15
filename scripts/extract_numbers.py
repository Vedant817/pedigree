#!/usr/bin/env python3
"""extract_numbers.py - regenerate the machine block of docs/NUMBERS.md.

Sources, in order:
1. evals/results/numbers.json  (written by `make eval`; keys = value or {value, source})
2. curated static facts already in docs/NUMBERS.md are preserved.

Until the evaluation harness exists (F-14), this script reports and exits 0 without
touching the file - it never invents a number.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BEGIN = "<!-- NUMBERS:BEGIN -->"
END = "<!-- NUMBERS:END -->"


def main() -> int:
    root = Path.cwd()
    numbers = root / "docs" / "NUMBERS.md"
    if not numbers.exists():
        print("[extract-numbers] docs/NUMBERS.md missing; nothing to do")
        return 0
    src = root / "evals" / "results" / "numbers.json"
    if not src.exists():
        print(f"[extract-numbers] no {src.relative_to(root)} yet (F-14 not run); NUMBERS.md unchanged")
        return 0

    data = json.loads(src.read_text(encoding="utf-8"))
    lines: list[str] = []
    for key in sorted(data):
        entry = data[key]
        if isinstance(entry, dict):
            value, source = entry.get("value"), entry.get("source", "evals")
        else:
            value, source = entry, "evals"
        lines.append(f"{key} = {value}   # {source}")

    text = numbers.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("[extract-numbers] NUMBERS.md lacks markers; refusing to edit")
        return 1
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    updated = f"{head}{BEGIN}\n" + "\n".join(lines) + f"\n{END}{tail}"
    numbers.write_text(updated, encoding="utf-8")
    print(f"[extract-numbers] wrote {len(lines)} value(s) into docs/NUMBERS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
