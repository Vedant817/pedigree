"""Revoke engine (the core algorithm): barrier -> quarantine fixpoint -> compute_final ->
chunked write -> verify. Crash-safe by construction: if the process dies mid-way, every
affected node is already `quarantined` (excluded from retrieval) and the `Revocation` row
stays `running`, so `resume_incomplete()` finishes the job idempotently.

Also: dry-run (no writes, same numbers), reinstate, and the per-tenant in-process lock.
"""

from __future__ import annotations

import collections
import threading
import time

from ..config import LIMITS, REVOCABLE, validate_tenant
from ..db import queries as Q
from ..db.client import Db, Trace, chunks
from ..errors import InvalidArgument, NotFoundInGraph, PedigreeError, TooLarge
from .compute import compute_final
from .ingest import new_id, node_exists, now_ms

MAX_FIXPOINT_ITERS = 10
MAX_VERIFY_ITERS = 5

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def tenant_lock(tenant: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(tenant)
        if lock is None:
            lock = threading.RLock()
            _locks[tenant] = lock
        return lock


# --- discovery --------------------------------------------------------------
def discover(db: Db, gname: str, roots, *, trace: Trace | None = None) -> dict[str, str]:
    """All descendants of every root (BFS over FEEDS, unbounded). Returns {id: status}."""
    out: dict[str, str] = {}
    for r in roots:
        res = db.ro_query(gname, Q.Q_DESCENDANTS, {"id": r, "depth": -1}, op="revoke.discover", trace=trace)
        for node_id, status in res.result_set or []:
            out[node_id] = status
    return out


def revoked_roots(db: Db, gname: str, *, trace: Trace | None = None) -> set[str]:
    res = db.ro_query(gname, Q.Q_REVOKED_ROOTS, {}, op="revoke.roots", trace=trace)
    return {row[0] for row in res.result_set or []}


def read_structure(db: Db, gname: str, ids, *, trace: Trace | None = None):
    """Read parents (DERIVED_FROM) and corroboration (CORROBORATED_BY) for `ids`, chunked."""
    parents: dict[str, list[str]] = collections.defaultdict(list)
    support: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    ids = list(ids)
    for ch in chunks(ids):
        res = db.ro_query(gname, Q.Q_PARENTS_OF, {"ids": ch}, op="revoke.parents", trace=trace)
        for child, parent in res.result_set or []:
            parents[child].append(parent)
        res = db.ro_query(gname, Q.Q_SUPPORT_OF, {"ids": ch}, op="revoke.support", trace=trace)
        for mem, src, status in res.result_set or []:
            support[mem].append((src, status))
    return parents, support


def plan(db: Db, gname: str, roots, *, seeds=None, trace: Trace | None = None):
    """Read-only: current statuses + the final statuses a real revoke would produce."""
    statuses = discover(db, gname, seeds if seeds is not None else roots, trace=trace)
    parents, support = read_structure(db, gname, list(statuses), trace=trace)
    final = compute_final(set(statuses), set(roots), parents, support, statuses)
    return statuses, final


# --- public API -------------------------------------------------------------
def revoke(
    db: Db,
    gname: str,
    tenant: str,
    *,
    root_id: str,
    reason: str = "",
    dry_run: bool = False,
    kind: str = "revoke",
    trace: Trace | None = None,
    hook=None,
) -> dict:
    if kind not in ("revoke", "supersede"):
        raise InvalidArgument("invalid revocation kind")
    tenant = validate_tenant(tenant)
    if len(reason) > LIMITS["reason_len"]:
        raise TooLarge("reason too long", detail={"limit": LIMITS["reason_len"]})
    exists, labels = node_exists(db, gname, root_id, trace)
    if not exists:
        raise NotFoundInGraph("unknown id", detail={"id": root_id})
    if not (set(labels) & set(REVOCABLE)):
        raise InvalidArgument("only Source or Memory can be revoked", detail={"id": root_id})

    t0 = time.perf_counter()
    if dry_run:
        roots = revoked_roots(db, gname, trace=trace) | {root_id}
        statuses, final = plan(db, gname, roots, trace=trace)
        would_taint = [i for i, f in final.items() if f.status == "tainted" and statuses.get(i) != "tainted"]
        would_preserve = [i for i, f in final.items() if f.status == "preserved" and statuses.get(i) != "preserved"]
        would_ok = [i for i, f in final.items() if f.status == "ok" and statuses.get(i) != "ok"]
        actions, irreversible, artifacts = _effects(db, gname, final, trace)
        return {
            "dry_run": True,
            "root_id": root_id,
            "counts": {
                "would_taint": len(would_taint),
                "would_preserve": len(would_preserve),
                "would_keep_ok": len(would_ok),
            },
            "actions": actions,
            "irreversible": irreversible,
            "artifacts": artifacts,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    with tenant_lock(tenant):
        rid = new_id("rev")
        res = db.query(
            gname,
            Q.Q_REVOKE_ROOT,
            {"id": root_id, "rid": rid, "tenant": tenant, "why": reason, "kind": kind, "now": now_ms()},
            op="revoke.root",
            trace=trace,
        )
        if not res.result_set:
            latest = db.ro_query(gname, Q.Q_REVOCATION_LATEST, {"id": root_id}, op="revoke.latest", trace=trace)
            row = latest.result_set[0] if latest.result_set else None
            # P-011 (A1): a root that was revoked but whose Revocation is still `running`
            # (process died mid-flight) is NOT a no-op. Finish it instead: resolve() is
            # idempotent by construction (re-quarantine + recompute + write final), so
            # re-running it matches a clean run.
            if row is not None and row[1] == "running":
                finished = resume_incomplete(db, gname, trace=trace)
                resumed_row = next((r for r in finished if r.get("revocation_id") == row[0]), None)
                if resumed_row is not None:
                    resumed_row = dict(resumed_row)
                    resumed_row.update({
                        "idempotent": False,
                        "resumed": True,
                        "root_id": root_id,
                        "kind": kind,
                        "reason": reason,
                        "ms": round((time.perf_counter() - t0) * 1000, 1),
                    })
                    return resumed_row
            return {
                "idempotent": True,
                "root_id": root_id,
                "revocation_id": row[0] if row else None,
                "state": row[1] if row else None,
                "counts": {"tainted": 0, "preserved": 0, "ok": 0, "quarantined": 0},
                "actions": [],
                "irreversible": [],
                "artifacts": [],
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        roots = revoked_roots(db, gname, trace=trace)
        statuses, final = resolve(db, gname, roots, trace=trace, hook=hook)
        out = _finish(db, gname, rid, statuses, final, trace)
        out.update({"idempotent": False, "root_id": root_id, "kind": kind, "reason": reason})
        out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out


def resolve(db: Db, gname: str, roots, *, seeds=None, trace: Trace | None = None, hook=None):
    """Barrier fixpoint + support-preserving final statuses + verify loop. Returns (statuses, final).

    `hook` is a testing seam called once after the first discovery of the barrier fixpoint;
    tests use it to inject a concurrent ingest into the window the barrier must close.
    """
    final: dict = {}
    statuses: dict[str, str] = {}
    seeds = set(seeds if seeds is not None else roots)
    for iteration in range(MAX_FIXPOINT_ITERS):
        statuses = discover(db, gname, seeds, trace=trace)
        if hook is not None and iteration == 0:
            hook()
        todo = [i for i, st in statuses.items() if st in ("ok", "preserved")]
        if not todo:
            break
        for ch in chunks(todo):
            db.query(gname, Q.Q_QUARANTINE_CHUNK, {"ids": ch}, op="revoke.quarantine", trace=trace)
    else:
        raise PedigreeError("revocation barrier did not converge", detail={"iterations": MAX_FIXPOINT_ITERS})

    for _ in range(MAX_VERIFY_ITERS):
        statuses = discover(db, gname, seeds, trace=trace)
        parents, support = read_structure(db, gname, list(statuses), trace=trace)
        final = compute_final(set(statuses), set(roots), parents, support, statuses)
        batch = [[i, [f.status, f.taint_parent]] for i, f in final.items()]
        for ch in chunks(batch):
            db.query(gname, Q.Q_WRITE_FINAL, {"b": ch}, op="revoke.write", trace=trace)
        statuses = discover(db, gname, seeds, trace=trace)
        if not any(st == "quarantined" for st in statuses.values()):
            break
    return statuses, final


def _effects(db: Db, gname: str, final, trace: Trace | None):
    """Actions + irreversible actions + affected artifacts for a final-status map."""
    tainted = [i for i, f in final.items() if f.status == "tainted"]
    actions: list[dict] = []
    for ch in chunks(tainted):
        res = db.ro_query(gname, Q.Q_ACTION_DETAILS, {"ids": ch}, op="revoke.actions", trace=trace)
        for a_id, tool, summary, effect, risk, arts, _status in res.result_set or []:
            actions.append(
                {
                    "id": a_id,
                    "tool": tool,
                    "summary": summary,
                    "effect": effect,
                    "risk": risk,
                    "artifacts": list(arts or []),
                }
            )
    irreversible = [a for a in actions if a["effect"] == "irreversible"]
    artifacts: set[str] = set()
    for a in actions:
        artifacts.update(a["artifacts"])
    touched = [i for i, f in final.items() if f.status in ("tainted", "preserved")]
    for ch in chunks(touched):
        res = db.ro_query(gname, Q.Q_MEMORY_ARTIFACTS, {"ids": ch}, op="revoke.artifacts", trace=trace)
        for _mid, artifact, _st in res.result_set or []:
            if artifact:
                artifacts.add(artifact)
    return actions, irreversible, sorted(artifacts)


def _finish(db: Db, gname: str, rid: str, statuses: dict[str, str], final, trace: Trace | None) -> dict:
    counts = collections.Counter(f.status for f in final.values())
    quarantined_left = sum(1 for st in statuses.values() if st == "quarantined")
    actions, irreversible, artifacts = _effects(db, gname, final, trace)
    db.query(
        gname,
        Q.Q_REVOCATION_SET_STATE,
        {
            "rid": rid,
            "state": "done",
            "now": now_ms(),
            "t": counts.get("tainted", 0),
            "p": counts.get("preserved", 0),
            "a": len(actions),
        },
        op="revoke.finish",
        trace=trace,
    )
    return {
        "revocation_id": rid,
        "state": "done",
        "counts": {
            "tainted": counts.get("tainted", 0),
            "preserved": counts.get("preserved", 0),
            "ok": counts.get("ok", 0),
            "quarantined_left": quarantined_left,
        },
        "actions": actions,
        "irreversible": irreversible,
        "artifacts": artifacts,
    }


def reinstate(
    db: Db,
    gname: str,
    tenant: str,
    *,
    root_id: str,
    dry_run: bool = False,
    trace: Trace | None = None,
) -> dict:
    """Undo one revocation: recompute statuses around the reinstated root WITHOUT erasing other
    revoked roots (P-012).

    The previous implementation blanket-reset the root's whole descendant set to 'ok' and only
    then re-resolved the remaining roots, which silently erased any independent revocation. This
    version flips only the explicitly reinstated root and re-derives its dependents via
    resolve(roots=remaining revokes, seeds=remaining ∪ {root_id}); `compute_final` keeps remaining
    revoked roots 'revoked' (Q_WRITE_FINAL has `WHERE n.status <> 'revoked'`).
    """
    tenant = validate_tenant(tenant)
    exists, labels = node_exists(db, gname, root_id, trace)
    if not exists:
        raise NotFoundInGraph("unknown id", detail={"id": root_id})
    if not (set(labels) & set(REVOCABLE)):
        raise InvalidArgument("only Source or Memory can be reinstated", detail={"id": root_id})

    with tenant_lock(tenant):
        descendants = discover(db, gname, [root_id], trace=trace)
        roots = revoked_roots(db, gname, trace=trace)
        if dry_run:
            remaining = roots - {root_id}
            statuses, final = plan(db, gname, remaining, seeds=remaining | {root_id}, trace=trace)
            counts = collections.Counter(f.status for f in final.values())
            return {
                "dry_run": True,
                "root_id": root_id,
                "would_reset": len(descendants) + 1,
                "remaining_roots": len(remaining),
                "counts": {
                    "tainted": counts.get("tainted", 0),
                    "preserved": counts.get("preserved", 0),
                    "ok": counts.get("ok", 0),
                },
            }
        # Supersede any concurrent running revoke rows for this root (diagnosability).
        db.query(gname, Q.Q_REVOCATION_SUPERSEDE, {"id": root_id, "now": now_ms()},
                 op="reinstate.supersede", trace=trace)
        # CAS: only flips when the root is currently revoked; returns no row otherwise.
        new_rid = new_id("rein")
        res = db.query(
            gname,
            Q.Q_REINSTATE_ROOT,
            {"id": root_id, "rid": new_rid, "tenant": tenant, "why": "reinstate", "now": now_ms()},
            op="reinstate.root",
            trace=trace,
        )
        if not res.result_set:
            # Not currently revoked: idempotent, nothing to recompute.
            return {
                "dry_run": False,
                "idempotent": True,
                "root_id": root_id,
                "revocation_id": None,
                "state": "not-revoked",
                "remaining_roots": len(roots - {root_id}),
                "counts": {"tainted": 0, "preserved": 0, "ok": 0},
            }
        remaining = roots - {root_id}
        statuses, final = resolve(db, gname, remaining, seeds=remaining | {root_id}, trace=trace)
        counts = collections.Counter(f.status for f in final.values())
        out = _finish(db, gname, new_rid, statuses, final, trace)
        out.update({"dry_run": False, "idempotent": False, "root_id": root_id,
                    "remaining_roots": len(remaining), "reset": len(descendants)})
        return out


def resume_incomplete(db: Db, gname: str, *, trace: Trace | None = None) -> list[dict]:
    """Finish every running Revocation."""
    res = db.ro_query(gname, Q.Q_RUNNING_REVOCATIONS, {}, op="revoke.running", trace=trace)
    out: list[dict] = []
    for rid, _root_id, tenant in res.result_set or []:
        with tenant_lock(tenant or gname):
            roots = revoked_roots(db, gname, trace=trace)
            statuses, final = resolve(db, gname, roots, trace=trace)
            out.append(_finish(db, gname, rid, statuses, final, trace))
    return out


def report(db: Db, gname: str, *, trace: Trace | None = None) -> dict:
    """Status summary used by the UI header and by tests."""
    res = db.ro_query(gname, Q.Q_STATUS_COUNTS, {}, op="revoke.report", trace=trace)
    by_status = {row[0]: int(row[1]) for row in res.result_set or []}
    res = db.ro_query(gname, Q.Q_REVOCATION_COUNTS, {}, op="revoke.report", trace=trace)
    revocations = {row[0]: int(row[1]) for row in res.result_set or []}
    return {"by_status": by_status, "revocations": revocations}
