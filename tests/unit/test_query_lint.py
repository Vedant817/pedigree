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

# Two labelled-anchor shapes, both quadratic without the :Node(id) index:
#   1. property map - `MATCH (x:Memory {id:...})` / `MERGE (:Memory {id:...})`;
#   2. separate WHERE - `MATCH (x:Memory) WHERE x.id = ...` (optional per-pattern
#      parentheses and a leading node/relationship pattern list).
# Formatting-tolerant and case-insensitive (P010-QA-1 rounds 1-3). SCOPE: the lint
# guards the canonical spellings and their near variants - the shapes this codebase
# has used or could plausibly introduce. Deliberate grammar paraphrase beyond that
# is accepted residual (comments inside the pattern, backtick quoting, reversed
# operand order `WHERE $m = m.id`, or extra Cypher clauses between the anchor and
# the WHERE); none of them exist in src/ and the behavioural guard is the
# EXPLAIN/perf gate plus code review, not this regex.
_TYPE_LABELS = r"(?:Memory|Action|Source|Session|Agent|Revocation)"
LABEL_ANCHOR = re.compile(
    rf"(?:match|merge)\s*\(\s*\w*\s*:\s*{_TYPE_LABELS}\s*\{{\s*id\s*:",
    re.IGNORECASE,
)
WHERE_ID_ANCHOR = re.compile(
    rf"\(\s*(\w+)\s*:\s*{_TYPE_LABELS}\s*\)"
    rf"\s*(?:,\s*\([^()]*\)(?:\s*-?\s*\[[^\]]*\]\s*-?\s*>?\s*\([^()]*\))*\s*)*"
    rf"where\s+\(*\s*\1\s*\.\s*id\s*\)*\s*=",
    re.IGNORECASE,
)
ANCHOR_PATTERNS = (LABEL_ANCHOR, WHERE_ID_ANCHOR)


def test_no_label_anchored_id_lookups():
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in ANCHOR_PATTERNS:
            for m in pattern.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {m.group(0)}...")
    assert not offenders, (
        "id anchors must be written on :Node so the unique index is used "
        "(MATCH (x:Node {id:...}) WHERE x:<Label>):\n" + "\n".join(sorted(set(offenders)))
    )


def test_anchor_regex_catches_formatting_variants():
    """P010-QA-1 rounds 1+2: no valid label-scanning shape may evade the lint."""
    variants = (
        "MATCH (m:Memory {id:$m})",
        "match (m:Memory {id:$m})",
        "MATCH (m : Memory { id : $m })",
        "MATCH (m:Memory{id:$m})",
        "MATCH( m:Session {id: $sess})",
        "MERGE (m:Memory {id:$m})",
        "MERGE (:Memory {id:$m})",
        "MATCH (:Memory {id:$m})",
        "MATCH (m:Memory) WHERE m.id = $m",
        "match (m : Action)\nwhere m . id = $m",
        "MATCH (m:Memory), (s:Source) WHERE m.id = $m",
        "MATCH (m:Memory) WHERE (m.id = $m)",
        "MATCH (m:Memory), (a:Action)-[:R]->(b) WHERE m.id = $m",
    )
    undetected = [v for v in variants if not any(p.search(v) for p in ANCHOR_PATTERNS)]
    assert not undetected, f"lint regex must catch: {undetected}"


def test_anchor_regex_ignores_safe_forms():
    """No false positives on index-backed or non-id forms."""
    safe = (
        "MATCH (m:Node {id:$m}) WHERE m:Memory",
        "MATCH (m:Node:Memory {id:$m})",  # :Node label present -> index-backed
        "MATCH (n:Memory {artifact_key:$k})",  # has its own index
        "MATCH (n:Node) WHERE n.id = $id",  # anchored on :Node via WHERE
        "MATCH (m:Memory) WHERE m.artifact_key = $k",
        "MATCH (s:Source) WHERE NOT s.id IN $ranked",
        "WHERE n:Memory",
        "MATCH (n:Node) WHERE n:Memory RETURN n.id",
    )
    flagged = [s for s in safe if any(p.search(s) for p in ANCHOR_PATTERNS)]
    assert not flagged, f"lint regex must not flag: {flagged}"
