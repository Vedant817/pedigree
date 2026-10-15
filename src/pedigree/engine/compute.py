"""Pure support-preserving status computation (no I/O) - the unit-testable oracle.

Semantics (docs/01 section 6.3): for every node reachable from a revoked root, in
topological order:
  bad(m)      = any DERIVED_FROM parent that is revoked/tainted (or still quarantined)
  bad(m)=[]   -> ok
  bad(m)!=[]  -> preserved if m has a healthy CORROBORATED_BY source, else tainted
`preserved` keeps the information retrievable but shows the supporting source; a node whose
only bad parent became `preserved` is simply `ok` (that is why the topological order matters).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass

BAD_STATUSES = ("revoked", "tainted", "quarantined")


@dataclass(frozen=True)
class FinalStatus:
    status: str  # ok | tainted | preserved
    taint_parent: str | None


class CycleError(ValueError):
    """The derivation graph is not a DAG (invariant violation)."""


def topological_order(
    nodes: set[str], parents: dict[str, list[str]]
) -> list[str]:
    """Kahn topological order over the subgraph induced by `nodes` (parents within nodes)."""
    indeg: dict[str, int] = {n: 0 for n in nodes}
    kids: dict[str, list[str]] = collections.defaultdict(list)
    for child in nodes:
        for parent in parents.get(child, []):
            if parent in nodes:
                indeg[child] += 1
                kids[parent].append(child)
    queue = collections.deque(sorted(n for n in nodes if indeg[n] == 0))
    order: list[str] = []
    while queue:
        x = queue.popleft()
        order.append(x)
        for k in kids[x]:
            indeg[k] -= 1
            if indeg[k] == 0:
                queue.append(k)
    if len(order) != len(nodes):
        raise CycleError("cycle in derivation graph")
    return order


def compute_final(
    members: set[str],
    roots: set[str],
    parents: dict[str, list[str]],
    support: dict[str, list[tuple[str, str]]],
    statuses: dict[str, str],
) -> dict[str, FinalStatus]:
    """Return the final status of every member that is not itself a revoked root.

    members  : ids in the closure (descendants of every revoked root)
    roots    : ids of revoked roots
    parents  : child id -> parent ids (from DERIVED_FROM)
    support  : memory id -> [(source id, source status)] (from CORROBORATED_BY)
    statuses : current status of every member
    """
    order = topological_order(members, parents)
    final: dict[str, FinalStatus] = {}

    def is_bad(parent: str) -> bool:
        resolved = final.get(parent)
        if resolved is not None:
            return resolved.status == "tainted"
        if parent in roots:
            return True
        return statuses.get(parent) in BAD_STATUSES

    for node in order:
        if node in roots or statuses.get(node) == "revoked":
            continue  # revoked roots keep their status; never rewritten
        bad = [p for p in parents.get(node, []) if is_bad(p)]
        if not bad:
            final[node] = FinalStatus("ok", None)
            continue
        healthy = [s for s, st in support.get(node, []) if st == "ok"]
        final[node] = FinalStatus("preserved" if healthy else "tainted", bad[0])
    return final
