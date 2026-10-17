"""P-022 observability: metric families and the JSON access log.

One process, one registry: the default `prometheus_client.REGISTRY` exposed by
`api/routes/metrics.py`. Nothing here may record or label credential material —
labels are tenant ids, static op names and fixed outcome words.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

_access = logging.getLogger("pedigree.access")


def _metric(factory, name: str):
    """Create a collector, reusing one already registered under this name.

    The package can be imported under a second module identity (`src.pedigree...`
    alongside `pedigree...`, which `tests/evals` does); each identity would
    otherwise try to register the same timeseries in the shared default registry
    and the second import would die with DuplicateTimeseries. Reuse keeps both
    identities counting into one collector.
    """
    mapping = getattr(REGISTRY, "_names_to_collectors", {})
    for sample in (name, f"{name}_total", f"{name}_count"):
        collector = mapping.get(sample)
        if collector is not None:
            return collector
    return factory()


#: FalkorDB operation latency, labelled by the static op name (`revoke.write`, `gate.nodes`, ...).
QUERY_SECONDS = _metric(lambda: Histogram(
    "pedigree_query_seconds",
    "FalkorDB operation latency in seconds.",
    ["op"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
), "pedigree_query_seconds")

#: Revocation outcomes: done | resumed | idempotent.
REVOCATIONS = _metric(
    lambda: Counter("pedigree_revocations_total", "Revocations by outcome.", ["status"]),
    "pedigree_revocations_total")

#: Gate decisions by verdict (allow | warn | reverify | block, the values in the gate result).
GATE_DECISIONS = _metric(
    lambda: Counter("pedigree_gate_decisions_total", "Gate decisions by verdict.", ["decision"]),
    "pedigree_gate_decisions_total")

#: Node counts by tenant and status. Updated when a tenant's report is served, not at
#: scrape time (documented in docs/fixes/P-022.md): the shared database holds hundreds
#: of tenant graphs and a full scan per scrape is not affordable.
NODES = _metric(
    lambda: Gauge("pedigree_nodes", "Nodes observed per tenant and status.", ["tenant", "status"]),
    "pedigree_nodes")


def observe_query(op: str, ms: float) -> None:
    """Record one FalkorDB operation in `pedigree_query_seconds`."""
    QUERY_SECONDS.labels(op=op or "query").observe(ms / 1000.0)


def count_revocation(status: str) -> None:
    """Count one completed revocation: done | resumed | idempotent."""
    REVOCATIONS.labels(status=status).inc()


def count_gate(decision: str) -> None:
    """Count one gate decision by verdict."""
    GATE_DECISIONS.labels(decision=decision).inc()


def update_nodes(tenant: str, by_status: Mapping[str, int] | None) -> None:
    """Refresh the per-tenant node gauge from a served report."""
    for status, count in (by_status or {}).items():
        NODES.labels(tenant=tenant, status=status).set(count)


def access_record(
    *,
    request_id: str | None,
    method: str,
    path: str,
    status: int,
    ms: float,
    tenant: str | None = None,
    op: str | None = None,
) -> None:
    """Emit one JSON access line. Never called with headers, bodies or query strings."""
    record: dict[str, object] = {
        "request_id": request_id,
        "method": method,
        "path": path[:200],
        "status": status,
        "ms": round(ms, 2),
    }
    if tenant is not None:
        record["tenant"] = tenant
    if op is not None:
        record["op"] = op
    _access.info(json.dumps(record, sort_keys=True))
