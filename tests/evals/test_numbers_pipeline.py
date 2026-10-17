"""The regeneration path must not drop a published number.

`docs/NUMBERS.md` is rewritten between its markers from `evals/results/numbers.json`,
which `make eval` writes after merging `evals/static_numbers.py`. A key published in
NUMBERS.md but missing from both is silently deleted on the next run and then fails
`scripts/check_numbers.py` (the P-006 sign-off defect). This test pins the invariant.
"""
from __future__ import annotations

import json
from pathlib import Path

from evals.static_numbers import STATIC_NUMBERS

ROOT = Path(__file__).resolve().parents[2]
NUMBERS = ROOT / "docs" / "NUMBERS.md"
RESULTS = ROOT / "evals" / "results" / "numbers.json"

BEGIN = "<!-- NUMBERS:BEGIN -->"
END = "<!-- NUMBERS:END -->"


def _published_keys() -> set[str]:
    text = NUMBERS.read_text(encoding="utf-8")
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    return {line.split("=", 1)[0].strip() for line in block.splitlines() if "=" in line}


def test_every_published_number_survives_regeneration():
    assert RESULTS.exists(), "evals/results/numbers.json is tracked; run `make eval`"
    produced = set(json.loads(RESULTS.read_text(encoding="utf-8")))
    missing = _published_keys() - produced - set(STATIC_NUMBERS)
    assert not missing, f"NUMBERS.md keys vanish on regeneration: {sorted(missing)}"
