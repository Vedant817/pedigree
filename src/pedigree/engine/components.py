"""Bounded weak-component summaries of tenant lineage using FalkorDB WCC."""
from ..db.client import Db, Trace
from ..db.queries import Q_WCC_SUMMARY
from ..errors import InvalidArgument


def weak_components(db: Db, gname: str, *, limit: int = 50, trace: Trace | None = None) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise InvalidArgument("component limit must be between 1 and 100")
    rows = db.ro_query(gname, Q_WCC_SUMMARY, {"limit": limit + 1},
                       op="audit.components", trace=trace).result_set or []
    return {"components": [{"component": int(row[0]), "nodes": int(row[1])}
                            for row in rows[:limit]],
            "truncated": len(rows) > limit,
            "note": "weak connectivity over derivation and corroboration; component IDs are snapshot-local"}
