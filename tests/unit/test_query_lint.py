"""Lint (P-010): every id anchor must match on `:Node(id)`, not on the type label.

FalkorDB has exactly one index for entity lookup - the unique `:Node(id)` index
(`db/schema.py` -> `Q_INDEX_NODE_ID`). A lookup written as `MATCH (m:Memory {id:...})`
cannot use it and degrades to a *Node By Label Scan*: measured on a 60k-node graph,
1000 ids took 3.7-5.5 s instead of 0.01 s, and the revoke cascade timed out above
~15-20k nodes (AUDIT.md P-010). The canonical shape is:

    MATCH (m:Node {id:...}) WHERE m:Memory ...

The plan-level guarantee ("Node By Index Scan", no "Node By Label Scan") is asserted
in `tests/perf/test_revoke_scaling.py` against a real FalkorDB.
"""

from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "pedigree"

# A labelled id anchor: `MATCH (x:Memory {id:` ... (any of the six type labels).
LABEL_ANCHOR = re.compile(r"MATCH \((\w+):(Memory|Action|Source|Session|Agent|Revocation) \{id\b")


def test_no_label_anchored_id_lookups():
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in LABEL_ANCHOR.finditer(text):
            lineno = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{path.relative_to(SRC)}:{lineno}: {m.group(0)}...")
    assert not offenders, (
        "id anchors must be written on :Node so the unique index is used "
        "(MATCH (x:Node {id:...}) WHERE x:<Label>):\n" + "\n".join(offenders)
    )
