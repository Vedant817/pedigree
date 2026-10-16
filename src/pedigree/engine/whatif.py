"""What-if: "what would revoking this do?" without touching the real graph (F-17).

`GRAPH.COPY` gives an atomic copy that keeps the indexes; we run the *real* revoke engine on the
copy for each root, diff the statuses against the original graph, and delete the copy in a
`finally` - so a what-if can never leave the tenant's lineage changed. Per-tenant concurrency is
capped. Only copies with expired lease metadata are reaped across processes; an
untracked graph is not evidence that its owner has stopped.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from ..config import LIMITS, graph_name, validate_id, whatif_graph_name
from ..db import queries as Q
from ..db.client import DB_EXC, Db, Trace
from ..errors import InvalidArgument, NotFoundInGraph, PedigreeError, Unavailable
from .revoke import revoke

MAX_CONCURRENT = 2
STALE_AFTER_S = 600  # 10 minutes
OWNER = secrets.token_hex(16)


@dataclass
class _Copy:
    token: str
    graph: str
    created_at: float
    active: bool = True


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
            # An old active call is still active. Failed cleanup also consumes a slot
            # until a later cleanup succeeds; never age capacity out silently.
            if len(state.copies) >= MAX_CONCURRENT:
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
            return {c.graph for c in state.copies.values() if c.active} if state else set()

    def cleanup_failed(self, tenant: str, token: str) -> None:
        with self._lock:
            self._tenants[tenant].copies[token].active = False

    def pending_cleanup(self, tenant: str) -> set[str]:
        with self._lock:
            state = self._tenants.get(tenant)
            return {c.graph for c in state.copies.values() if not c.active} if state else set()


REGISTRY = WhatIfRegistry()


def _statuses(db: Db, gname: str, trace: Trace | None = None) -> dict[str, str]:
    res = db.ro_query(gname, Q.Q_WHATIF_STATUSES, {}, op="whatif.statuses", trace=trace)
    return {row[0]: row[1] for row in res.result_set or []}


def _actions(db: Db, gname: str, trace: Trace | None = None) -> dict[str, dict]:
    res = db.ro_query(
        gname,
        Q.Q_WHATIF_ACTIONS,
        {}, op="whatif.actions", trace=trace)
    return {row[0]: {"tool": row[1], "summary": row[2], "effect": row[3], "risk": row[4],
                     "status": row[5]} for row in res.result_set or []}


def reap_stale(db: Db, tenant: str, gname: str, *, trace: Trace | None = None) -> list[str]:
    """Clean known inactive copies, or expired leases left by other processes.

    Copies from older versions without a lease require explicit operator cleanup;
    guessing their age could delete another worker's active simulation.
    """
    if gname != graph_name(tenant):
        raise InvalidArgument("tenant graph mismatch")
    prefix = f"{gname}:wi:"
    tracked = REGISTRY.tracked(tenant)
    pending = REGISTRY.pending_cleanup(tenant)
    reaped: list[str] = []
    try:
        graphs = db.list_graphs()
    except Exception:  # noqa: BLE001 - listing is best effort
        return reaped
    for graph in graphs:
        if not graph.startswith(prefix) or graph in tracked:
            continue
        token = graph[len(prefix):]
        try:
            if whatif_graph_name(tenant, token) != graph:
                continue
            if graph not in pending:
                lease = db.ro_query(graph, Q.Q_WHATIF_LEASE, {}, op="whatif.lease", trace=trace).result_set or []
                if not lease or lease[0][1] > int(time.time() * 1000):
                    continue
            db.select(graph).delete()
            REGISTRY.end(tenant, token)
            reaped.append(graph)
        except Exception:  # noqa: BLE001 - already gone
            continue
    return reaped


def whatif(db: Db, gname: str, tenant: str, roots: list[str], *, reason: str = "what-if",
           reap: bool = True, trace: Trace | None = None) -> dict:
    """Revoke `roots` on a copy and report what *would* change. Never writes to `gname`."""
    if gname != graph_name(tenant):
        raise InvalidArgument("tenant graph mismatch")
    if not isinstance(roots, list) or not roots:
        raise InvalidArgument("whatif needs at least one root")
    if len(roots) > LIMITS["whatif_roots"]:
        raise InvalidArgument("too many roots for one what-if", detail={"limit": LIMITS["whatif_roots"]})
    roots = list(dict.fromkeys(validate_id(root) for root in roots))
    if not isinstance(reason, str) or len(reason) > LIMITS["reason_len"]:
        raise InvalidArgument("invalid what-if reason")
    for root in roots:
        node = db.ro_query(gname, Q.Q_NODE_BY_ID, {"id": root}, op="whatif.root", trace=trace).result_set or []
        if not node:
            raise NotFoundInGraph("unknown what-if root")
        if not set(node[0][1]) & {"Source", "Memory"}:
            raise InvalidArgument("only Source or Memory can be revoked")
    if reap:
        reap_stale(db, tenant, gname, trace=trace)

    copy = REGISTRY.begin(tenant)
    t0 = time.perf_counter()
    result = None
    try:
        try:
            db.select(gname).copy(copy.graph)
        except DB_EXC as exc:
            raise Unavailable("what-if snapshot unavailable") from exc
        db.query(copy.graph, Q.Q_WHATIF_CREATE_LEASE,
                 {"owner": OWNER, "expires": int(time.time() * 1000) + STALE_AFTER_S * 1000},
                 op="whatif.lease_create", trace=trace)
        # Both sides of the diff come from the SAME atomic snapshot. Source writes
        # between earlier validation and GRAPH.COPY cannot appear as simulation effects.
        before = _statuses(db, copy.graph, trace)
        before_actions = _actions(db, copy.graph, trace)
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
        result = {
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
            "copy_deleted": False,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        return result
    finally:
        deleted = False
        try:
            # A failed/timed-out copy command may still have created the destination.
            # Its random name was allocated by this call, so cleanup is safe either way.
            db.select(copy.graph).delete()
            deleted = True
        except Exception:  # noqa: BLE001 - keep truthful status and retry capacity
            try:
                deleted = copy.graph not in db.list_graphs()
            except Exception:  # noqa: BLE001 - an unavailable DB cannot prove deletion
                deleted = False
            if result is not None:
                if not deleted:
                    result["cleanup_error"] = "snapshot cleanup failed; cleanup will be retried"
        if result is not None:
            result["copy_deleted"] = deleted
        if deleted:
            REGISTRY.end(tenant, copy.token)
        else:
            REGISTRY.cleanup_failed(tenant, copy.token)
