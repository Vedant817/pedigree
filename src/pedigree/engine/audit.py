"""audit_sources - which sources carry the most weight (F-18, docs/01 section 6.8).

PageRank is a *ranking*, not a count, so the exact descendant count from `algo.BFS` is reported
next to each score - the UI can show "ranked by influence (score) and by reach (count)" without
implying the two are the same thing.
"""
from __future__ import annotations

from ..db import queries as Q
from ..db.client import Db, Trace, chunks


def audit_sources(db: Db, gname: str, *, limit: int = 50, trace: Trace | None = None) -> dict:
    limit = max(1, min(int(limit), 50))
    res = db.ro_query(gname, Q.Q_PAGERANK_SOURCES, {"k": limit}, op="audit.pagerank", trace=trace)
    ranked = [(row[0], row[1], float(row[2])) for row in res.result_set or []]
    counts: dict[str, int] = {}
    for chunk in chunks([nid for nid, _kind, _score in ranked]):
        res = db.ro_query(gname, Q.Q_DESCENDANT_COUNTS, {"ids": chunk},
                          op="audit.descendants", trace=trace)
        for nid, n in res.result_set or []:
            counts[nid] = int(n)
    sources = [{"id": nid, "kind": kind, "pagerank": round(score, 6),
                "descendants": counts.get(nid, 0)} for nid, kind, score in ranked]
    return {"sources": sources, "limit": limit,
            "note": "pagerank is a heuristic ranking; descendants is the exact BFS reach count"}
