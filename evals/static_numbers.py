"""Static facts that must survive `make eval` (docs/03 rule zero: no hand-typed numbers).

Everything that appears in README/blog/video prose is a number with a *source*; these are the
ones that are not produced by an experiment but are still factual claims (versions, minimums,
the track count). `run_all.py` merges them into `numbers.json`, so `extract_numbers.py` never
silently drops them when it rewrites the block.
"""
from __future__ import annotations

import sys

STATIC_NUMBERS: dict[str, dict] = {
    "falkordb_version": {"value": "4.22.1", "source": "scripts/fetch-falkordb.sh (pinned)"},
    "falkordb_module_version": {"value": 42201,
                                "source": "pedigree db status / MODULE LIST on v4.22.1"},
    "python_min": {"value": "3.11", "source": "pyproject.toml requires-python"},
    "tracks_entered": {"value": 2, "source": "docs/DECISIONS.md ADR-000"},
}

if __name__ == "__main__":  # pragma: no cover - manual check
    for key, entry in STATIC_NUMBERS.items():
        print(f"{key} = {entry['value']}   # {entry['source']}")
    sys.exit(0)
