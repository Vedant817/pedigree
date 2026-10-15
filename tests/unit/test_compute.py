"""Property tests for the pure support-preserving computation.

`compute_final` is the product's semantics; this file checks it against an independently
written brute-force fixpoint on random DAGs (the eval oracle is a third implementation).
"""

from __future__ import annotations

import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pedigree.engine.compute import CycleError, compute_final, topological_order

BAD = ("revoked", "tainted", "quarantined")


def brute_force(members, roots, parents, support, statuses):
    """Independently written fixpoint (no topological order): iterate until stable."""
    final: dict[str, str] = {}
    for _ in range(len(members) + 3):
        changed = False
        for m in members:
            if m in roots or statuses.get(m) == "revoked":
                continue

            def parent_is_bad(p: str) -> bool:
                if p in final:
                    return final[p] == "tainted"
                return p in roots or statuses.get(p) in BAD

            bad = [p for p in parents.get(m, []) if parent_is_bad(p)]
            want = "ok" if not bad else ("preserved" if any(st_ == "ok" for _, st_ in support.get(m, [])) else "tainted")
            if final.get(m) != want:
                final[m] = want
                changed = True
        if not changed:
            break
    return final


# --- hand-written cases -----------------------------------------------------
def test_preserved_chain_keeps_children_ok():
    members = {"m1", "m2", "m3", "m4"}
    roots = {"s"}
    parents = {"m1": ["s"], "m2": ["s"], "m3": ["m1", "m2"], "m4": ["m2"]}
    support = {"m2": [("doc", "ok")]}
    statuses = {m: "quarantined" for m in members}
    final = compute_final(members, roots, parents, support, statuses)
    assert final["m1"].status == "tainted"
    assert final["m2"].status == "preserved"
    assert final["m3"].status == "tainted"  # depends on tainted m1
    assert final["m4"].status == "ok"  # only parent is preserved -> not bad
    assert final["m2"].taint_parent == "s"
    assert final["m1"].taint_parent == "s"


def test_weak_corroboration_does_not_preserve():
    members = {"m1"}
    final = compute_final(members, {"s"}, {"m1": ["s"]}, {"m1": [("doc", "revoked")]}, {"m1": "quarantined"})
    assert final["m1"].status == "tainted"


def test_roots_are_not_rewritten():
    members = {"s2"}
    final = compute_final(members, {"s", "s2"}, {"s2": ["s"]}, {}, {"s": "revoked", "s2": "revoked"})
    assert "s2" not in final


def test_cycle_is_rejected():
    with pytest.raises(CycleError):
        topological_order({"a", "b"}, {"a": ["b"], "b": ["a"]})


# --- property test ----------------------------------------------------------
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(min_value=1, max_value=9), st.integers(min_value=0, max_value=2**20))
def test_agrees_with_brute_force_on_random_dags(n_nodes, seed):
    rng = random.Random(seed)
    ids = [f"n{i}" for i in range(n_nodes)]
    parents = {}
    for i, node in enumerate(ids):
        if i == 0:
            parents[node] = []
            continue
        k = rng.randint(0, min(3, i))
        parents[node] = rng.sample(ids[:i], k)  # only earlier nodes -> acyclic
    roots = {n for n in ids if not parents[n] and rng.random() < 0.7} or {ids[0]}
    support = {
        n: [(f"doc{i}", rng.choice(["ok", "ok", "revoked"])) for i in range(rng.randint(0, 2))]
        for n in ids
    }
    statuses = {n: ("revoked" if n in roots else "quarantined") for n in ids}
    members = set(ids)

    mine = compute_final(members, roots, parents, support, statuses)
    theirs = brute_force(members, roots, parents, support, statuses)
    assert {k: v.status for k, v in mine.items()} == theirs
