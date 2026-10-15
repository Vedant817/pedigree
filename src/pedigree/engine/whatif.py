"""What-if: "what would revoking this do?" without touching the real graph (F-17).

`GRAPH.COPY` gives an atomic copy that keeps the indexes; we run the *real* revoke engine on the
copy for each root, diff the statuses against the original graph, and delete the copy in a
`finally` - so a what-if can never leave the tenant's lineage changed. Per-tenant concurrency is
capped, and copies that are not tracked in this process (a crash leftover) are treated as stale
and reaped.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from ..config import whatif_graph_name
from ..db.client import Db, Trace
from ..errors import InvalidArgument, PedigreeError
from .revoke import revoke

MAX_CONCURRENT = 2
STALE_AFTER_S = 600  # 10 minutes


@dataclass
class _Copy:
    token: str
    graph: str
    created_at: float


@dataclass
class _TenantState:
    copies: dict[str, _Copy] = field(default_factory=dict)


class WhatIfRegistry:
    """In-process tracking of live what-if copies (concurrency cap + stale reaping)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants: dict[str, _TenantState] = {}

    def begin(self, tenant: str) -> _Copy:
        with self._lock:
            state = self._tenants.setdefault(tenant, _TenantState())
            live = {t: c for t, c in state.copies.items()
                    if time.monotonic() - c.created_at < STALE_AFTER_S}
            if len(live) >= MAX_CONCURRENT:
                raise PedigreeError("too many concurrent what-ifs",
                                    code="rate_limited", detail={"limit": MAX_CONCURRENT})
            token = secrets.token_hex(4)
            copy = _Copy(token=token, graph=whatif_graph_name(tenant, token),
                         created_at=time.monotonic())
            state.copies[token] = copy
            return copy

    def end(self, tenant: str, token: str) -> None:
        with self._lock:
            state = self._tenants.get(tenant)
            if state is not None:
                state.copies.pop(token, None)
                if not state.copies:
                    self._tenants.pop(tenant, None)

    def tracked(self, tenant: str) -> set[str]:
        with self._lock:
            state = self._tenants.get(tenant)
            return {c.graph for c in state.copies.values()} if state else set()


REGISTRY = WhatIfRegistry()


def _statuses(db: Db, gname: str, trace: Trace | None = None) -> dict[str, str]:
    res = db.ro_query(gname, "MATCH (n:Node) RETURN n.id, n.status", {}, op="whatif.statuses", trace=trace)
    return {row[0]: row[1] for row in res.result_set or []}


def _actions(db: Db, gname: str, trace: Trace | None = None) -> dict[str, dict]:
    res = db.ro_query(
        gname,
        "MATCH (a:Action) RETURN a.id, a.tool, a.summary, a.effect, a.risk, a.status",
        {}, op="whatif.actions", trace=trace)
    return {row[0]: {"tool": row[1], "summary": row[2], "effect": row[3], "risk": row[4],
                     "status": row[5]} for row in res.result_set or []}


def reap_stale(db: Db, tenant: str, gname: str, *, trace: Trace | None = None) -> list[str]:
    """Delete what-if copies of this tenant that this process does not track (crash leftovers)."""
    prefix = f"{gname}:wi:"
    tracked = REGISTRY.tracked(tenant)
    reaped: list[str] = []
    try:
        graphs = db.list_graphs()
    except Exception:  # noqa: BLE001 - listing is best effort
        return reaped
    for graph in graphs:
        if not graph.startswith(prefix) or graph in tracked:
            continue
        try:
            db.select(graph).delete()
            reaped.append(graph)
        except Exception:  # noqa: BLE001 - already gone
            continue
    return reaped


def whatif(db: Db, gname: str, tenant: str, roots: list[str], *, reason: str = "what-if",
           reap: bool = True, trace: Trace | None = None) -> dict:
    """Revoke `roots` on a copy and report what *would* change. Never writes to `gname`."""
    if not roots:
        raise InvalidArgument("whatif needs at least one root")
    if len(roots) > 8:
        raise InvalidArgument("too many roots for one what-if", detail={"limit": 8})
    if reap:
        reap_stale(db, tenant, gname, trace=trace)

    before = _statuses(db, gname, trace)
    before_actions = _actions(db, gname, trace)
    copy = REGISTRY.begin(tenant)
    t0 = time.perf_counter()
    try:
        db.select(gname).copy(copy.graph)
        revocations = []
        for root in roots:
            res = revoke(db, copy.graph, tenant, root_id=root, reason=reason, dry_run=False)
            revocations.append({"root_id": root, "id": res.get("revocation_id"),
                                "counts": res.get("counts", {})})
        after = _statuses(db, copy.graph, trace)
        after_actions = _actions(db, copy.graph, trace)
        changed = sorted(nid for nid, status in after.items() if before.get(nid) != status)
        diff = {
            "would_taint": [n for n in changed if after[n] == "tainted"],
            "would_preserve": [n for n in changed if after[n] == "preserved"],
            "would_revoke": [n for n in changed if after[n] == "revoked"],
            "unchanged": sorted(nid for nid in after if before.get(nid) == after[nid]),
        }
        actions_changed = [dict({"id": aid}, **info) for aid, info in sorted(after_actions.items())
                            if before_actions.get(aid, {}).get("status") != info["status"]]
        irreversible = [a for a in actions_changed if a.get("effect") == "irreversible"]
        return {
            "whatif": True,
            "roots": list(roots),
            "revocations": revocations,
            "diff": diff,
            "counts": {"nodes_changed": len(changed),
                        "would_taint": len(diff["would_taint"]),
                        "would_preserve": len(diff["would_preserve"]),
                        "actions_affected": len(actions_changed),
                        "irreversible_affected": len(irreversible)},
            "actions": actions_changed,
            "irreversible": irreversible,
            "copy": copy.graph,
            "copy_deleted": True,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    finally:
        try:
            db.select(copy.graph).delete()
        except Exception:  # noqa: BLE001 - the copy must not survive a failure either
            pass
        REGISTRY.end(tenant, copy.token)
