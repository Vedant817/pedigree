"""Schema management + invariant checking.

- Index builds are asynchronous: every schema creation polls `CALL db.indexes()` until
  OPERATIONAL (GOTCHAS #4). The unique constraint on Node(id) is created after its
  supporting exact-match index and is never dropped (GOTCHAS #2).
- `check_invariants` is the product's graph-consistency oracle used by tests, QA and the
  scenario runner; it returns a list of human-readable violations (empty = healthy).
"""

from __future__ import annotations

import time

from ..config import REGISTRY_GRAPH, STATUS_ALL
from ..engine.compute import CycleError, topological_order
from . import queries as Q
from .client import Db

DDL_BENIGN = ("already", "exists", "duplicate", "index supports constraint")


def _operational(row) -> bool:
    for cell in row:
        s = cell.decode() if isinstance(cell, bytes) else str(cell)
        if s.upper().startswith("OPERATIONAL"):
            return True
    return False


def wait_indexes(db: Db, gname: str, timeout: float = 30.0) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        rows = db.ro_query(gname, Q.Q_INDEXES, {}, op="schema.indexes").result_set or []
        if all(_operational(r) for r in rows):
            return time.time() - t0
        time.sleep(0.1)
    raise TimeoutError(f"indexes not operational after {timeout}s on {gname}")


def create_index(db: Db, gname: str, stmt: str) -> None:
    ok, err = db.try_query(gname, stmt)
    if not ok and not any(b in err.lower() for b in DDL_BENIGN):
        raise RuntimeError(f"index creation failed: {err}")


def create_unique_constraint(db: Db, gname: str, label: str = "Node", prop: str = "id") -> None:
    try:
        db.admin_raw("GRAPH.CONSTRAINT", "CREATE", gname, "UNIQUE", "NODE", label, "PROPERTIES", "1", prop)
    except Exception as exc:  # noqa: BLE001 - idempotent DDL
        if not any(b in str(exc).lower() for b in DDL_BENIGN):
            raise RuntimeError(f"constraint creation failed: {exc}") from exc


def _has_index(db: Db, gname: str, label: str, prop: str) -> bool:
    for row in db.ro_query(gname, Q.Q_INDEXES, {}, op="schema.indexes").result_set or []:
        cells = [c.decode() if isinstance(c, bytes) else str(c) for c in row]
        if any(label == c for c in cells) and any(prop == c for c in cells):
            return True
    return False


def ensure_source_identity(db: Db, gname: str) -> str:
    """Source identity index + composite unique constraint (consult 007 / ADR-008).

    One Source node per `(uri, content_hash)`: repeated reads of the same artifact converge,
    the same uri with a new content hash becomes a new version node. The uri-only constraint
    is deliberately NOT created - it rejects a legitimately changed page (measured on v4.22.1).
    Returns "ok", or "unavailable" when a pre-existing graph already holds duplicate pairs
    (recorded limitation; identity still works, the store just cannot enforce it).
    """
    for stmt in (Q.Q_INDEX_SOURCE_URI, Q.Q_INDEX_SOURCE_HASH):
        prop = "uri" if stmt is Q.Q_INDEX_SOURCE_URI else "content_hash"
        if not _has_index(db, gname, "Source", prop):
            create_index(db, gname, stmt)
    try:
        wait_indexes(db, gname)
    except TimeoutError:
        return "unavailable"
    try:
        db.admin_raw("GRAPH.CONSTRAINT", "CREATE", gname, "UNIQUE", "NODE", "Source",
                     "PROPERTIES", "2", "uri", "content_hash")
    except Exception as exc:  # noqa: BLE001 - idempotent DDL, or duplicate data
        msg = str(exc).lower()
        if any(b in msg for b in DDL_BENIGN):
            return "ok"
        if "constraint" in msg or "duplicate" in msg:
            return "unavailable"
        raise RuntimeError(f"source identity constraint creation failed: {exc}") from exc
    return "ok"


def ensure_schema(db: Db, gname: str, *, label: str = "Node") -> dict:
    """Idempotent per-tenant schema. Returns {index_wait_s, n_indexes, source_identity}."""
    t0 = time.time()
    create_index(db, gname, Q.Q_INDEX_NODE_ID if label == "Node" else Q.Q_INDEX_TENANT_ID)
    if label == "Node":
        create_index(db, gname, Q.Q_INDEX_CAPTURE_ID)
        create_index(db, gname, Q.Q_INDEX_MEMORY_ARTIFACT)
        create_index(db, gname, Q.Q_INDEX_ACTION_ARTIFACT)
        create_index(db, gname, Q.Q_INDEX_REVOCATION_ROOT)
        create_index(db, gname, Q.Q_INDEX_REVOCATION_STATE)
    else:
        for statement in (Q.Q_INDEX_TENANT_AGENT_DIGEST, Q.Q_INDEX_TENANT_OPERATOR_DIGEST,
                          Q.Q_INDEX_TENANT_LEGACY_DIGEST):
            create_index(db, gname, statement)
    wait_indexes(db, gname)
    create_unique_constraint(db, gname, label=label, prop="id")
    wait_indexes(db, gname)
    identity = ensure_source_identity(db, gname) if label == "Node" else "n/a"
    rows = db.ro_query(gname, Q.Q_INDEXES, {}, op="schema.indexes").result_set or []
    return {"index_wait_s": round(time.time() - t0, 3), "n_indexes": len(rows),
            "source_identity": identity}


def ensure_registry_schema(db: Db) -> dict:
    """Registry IDs and nullable role digests, with operational exact-match indexes."""
    ensure_schema(db, REGISTRY_GRAPH, label="Tenant")
    return {"graph": REGISTRY_GRAPH}


def node_count(db: Db, gname: str) -> int:
    res = db.ro_query(gname, Q.Q_INV_COUNT_NODES, {}, op="inv.count")
    return int(res.result_set[0][0]) if res.result_set else 0


def _count(db: Db, gname: str, cypher: str, params: dict | None = None) -> int:
    res = db.ro_query(gname, cypher, params or {}, op="inv")
    return int(res.result_set[0][0]) if res.result_set else 0


def check_invariants(
    db: Db,
    gname: str,
    expected_tenant: str | None = None,
    *,
    max_edges_for_cycle_check: int = 50_000,
) -> list[str]:
    """Return a list of invariant violations (empty list = healthy)."""
    violations: list[str] = []
    n_total = node_count(db, gname)

    checks: list[tuple[str, str, dict | None]] = [
        (Q.Q_INV_CAPTURE_SHAPE, "malformed capture receipt", None),
        (Q.Q_INV_NOT_NODE, "node without :Node label", None),
        (Q.Q_INV_BAD_TYPE, "node without a known type label", None),
        (Q.Q_INV_MULTI_TYPE, "node with more than one type label", None),
        (Q.Q_INV_BAD_STATUS, "node with unknown status", {"allowed": list(STATUS_ALL)}),
        (Q.Q_INV_MISSING_STATUS, "node without a status property", None),
        (Q.Q_INV_NO_ID, "node without id", None),
        (Q.Q_INV_OK_HAS_NO_BAD_PARENT, "ok node has bad parent", None),
        (Q.Q_INV_MISSING_FEEDS, "DERIVED_FROM without mirrored FEEDS", None),
        (Q.Q_INV_MISSING_DERIVED, "FEEDS without mirrored DERIVED_FROM", None),
        (Q.Q_INV_TAINTED_NO_PARENT, "tainted node without taint_parent", None),
        (Q.Q_INV_TAINTED_PARENT_MISSING, "tainted node with a taint_parent that does not exist", None),
        (Q.Q_INV_TAINTED_PARENT_HEALTHY, "tainted node whose taint_parent is healthy", None),
        (Q.Q_INV_PRESERVED_NO_SUPPORT, "preserved memory without any corroborating source", None),
        (Q.Q_INV_PRESERVED_WEAK_SUPPORT, "preserved memory without a healthy corroborating source", None),
        (Q.Q_INV_REVOKED_SHAPE, "revoked node that is not Source/Memory or lacks revoked_at", None),
        (Q.Q_INV_REVOKED_ORPHAN, "node carrying revoked_at but not marked revoked (P-012 clobbered root)", None),
    ]
    if expected_tenant is not None:
        checks.append((Q.Q_INV_BAD_TENANT, "node with a tenant that is not the graph's tenant", {"tenant": expected_tenant}))

    for cypher, label, params in checks:
        try:
            c = _count(db, gname, cypher, params)
        except Exception as exc:  # noqa: BLE001 - invariant check must not crash the caller
            violations.append(f"{label}: check failed ({type(exc).__name__})")
            continue
        if c:
            violations.append(f"{label}: {c}")

    if n_total <= max_edges_for_cycle_check:
        rows = db.ro_query(gname, Q.Q_INV_EDGES, {}, op="inv.edges").result_set or []
        parents: dict[str, list[str]] = {}
        nodes: set[str] = set()
        for a, b in rows:
            parents.setdefault(a, []).append(b)
            nodes.add(a)
            nodes.add(b)
        try:
            topological_order(nodes, parents)
        except CycleError:
            violations.append("derivation graph contains a cycle")

    # P-024: quarantined nodes without a running Revocation are stragglers
    try:
        running = db.ro_query(gname, Q.Q_RUNNING_REVOCATIONS, {}, op="inv").result_set or []
    except Exception:  # noqa: BLE001
        running = []
    if not running:
        try:
            quarantined_count = db.ro_query(
                gname, "MATCH (n:Node {status:'quarantined'}) RETURN count(n) AS n", {},
                op="inv.q", ).result_set or []
            quarantined_count = int(quarantined_count[0][0]) if quarantined_count else 0
        except Exception:  # noqa: BLE001
            quarantined_count = 0
        if quarantined_count:
            violations.append(f"quarantined node without a running Revocation: {quarantined_count}")
    return violations
