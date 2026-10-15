"""Independent ground-truth oracle for the docs/01 section 6.3 recurrence (docs/03 section 4).

Deliberately a *different* implementation from `engine/compute.py`: brute-force sweeps until
the status map stops changing, with no topological order and no shared helpers. A test asserts
the two agree on 1000 random small DAGs; if they ever disagree the eval reports the disagreement
instead of silently averaging it away.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BAD = ("revoked", "tainted", "quarantined")


@dataclass
class Truth:
    """Ground truth for one DAG with one revoked root.

    G: items truly dependent on the bad source *without* independent support (should be tainted)
    should_preserve: items dependent *with* independent support (should be preserved)
    ok: everything else
    A: affected actions (an action relying on a G member)
    """

    G: set[str] = field(default_factory=set)
    should_preserve: set[str] = field(default_factory=set)
    ok: set[str] = field(default_factory=set)
    A: set[str] = field(default_factory=set)
    reserved: set[str] = field(default_factory=set)  # actions relying on preserved-only branches

def _children_of(parents: dict[str, list[str]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for child, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(child)
    return children


def ground_truth(members, roots, parents, support, statuses) -> Truth:
    """Brute-force fixpoint over the same recurrence as docs/01 section 6.3.

    members: every id in the closure (descendants of the roots, roots included)
    roots: revoked root ids
    parents: child id -> parent ids
    support: memory id -> [(source id, source status)]
    statuses: current status of every member
    """
    status = {n: "revoked" if n in roots else "ok" for n in members}
    # a node whose only bad parent became `preserved` is `ok`; that needs iteration order
    # independence, so we sweep until nothing changes (max len(members) sweeps).
    for _ in range(len(members) + 1):
        changed = False
        for node in members:
            if node in roots or statuses.get(node) == "revoked":
                continue
            bad = [p for p in parents.get(node, []) if status.get(p) in ("tainted", "revoked")]
            if not bad:
                new = "ok"
            else:
                healthy = [s for s, st in support.get(node, []) if st == "ok"]
                new = "preserved" if healthy else "tainted"
            if new != status[node]:
                status[node] = new
                changed = True
        if not changed:
            break
    truth = Truth()
    for node in members:
        if node in roots:
            continue
        st = status[node]
        if st == "tainted":
            truth.G.add(node)
        elif st == "preserved":
            truth.should_preserve.add(node)
        else:
            truth.ok.add(node)
    return truth


def truth_for_dag(dag) -> Truth:
    """Model-level entry point: closure from the bad root, parents/support/statuses from the model."""
    members = set(dag.descendants(dag.bad))
    parents = {n: list(dag.parents.get(n, [])) for n in members}
    # support is independent support: the poisoned root itself never corroborates
    support = {n: [(s, "ok") for s in dag.support.get(n, []) if s != dag.bad]
               for n in members}
    statuses = {n: "ok" for n in members}
    truth = ground_truth(members, {dag.bad}, parents, support, statuses)
    # actions: an action relying on a G member is affected; relying only on preserved/ok is not
    for aid in dag.actions:
        if aid in truth.G:
            truth.A.add(aid)
    return truth
