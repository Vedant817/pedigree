"""P-012 hand cases + independence guard for the from-scratch global oracle.

Written from `docs/consults/008-p012-reinstate/oracle.md` §3/§4 (and the semantics pinned in
ADR-015). The oracle under test is `tests/oracle.py`; it must share no code with the engine
and must never read pre-existing statuses.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

import tests.oracle
from evals import gen
from evals.oracle import truth_for_dag
from tests.oracle import global_fixpoint


# --- hand cases (oracle.md section 4) ---------------------------------------
def test_preserved_frontier_keeps_children_ok():
    """A bad parent that is `preserved` is NOT bad: its children stay ok (the feature)."""
    nodes = {"s1": "source", "s2": "source", "m1": "memory", "c1": "memory", "c2": "action"}
    parents = {"m1": ("s1",), "c1": ("m1",), "c2": ("c1",)}
    support = {"m1": ("s2",)}
    status = global_fixpoint(nodes, parents, support, {"s1"})
    assert status == {
        "s1": "revoked",
        "s2": "ok",
        "m1": "preserved",
        "c1": "ok",
        "c2": "ok",
    }


def test_support_from_a_revoked_source_is_weak():
    """R3: only a support source whose status is ok preserves; a revoked source does not."""
    nodes = {"s1": "source", "s2": "source", "m1": "memory"}
    parents = {"m1": ("s1",)}
    support = {"m1": ("s2",)}
    status = global_fixpoint(nodes, parents, support, {"s1", "s2"})
    assert status["m1"] == "tainted"


def test_nested_roots_keep_root_precedence():
    """R7.1: a revoked root that is also a descendant stays revoked; its subtree is recomputed."""
    nodes = {"s1": "source", "s2": "source", "m1": "memory", "m2": "memory", "a1": "action"}
    parents = {"m1": ("s1",), "m2": ("m1",), "a1": ("m2",)}
    status = global_fixpoint(nodes, parents, {}, {"s1", "m1"})
    assert status["s1"] == "revoked"
    assert status["m1"] == "revoked", "root wins even as a descendant"
    assert status["m2"] == "tainted"
    assert status["a1"] == "tainted"


def test_nested_root_subtree_preserved_when_supported():
    nodes = {"s1": "source", "s2": "source", "m1": "memory", "m2": "memory"}
    parents = {"m1": ("s1",), "m2": ("m1",)}
    support = {"m2": ("s2",)}
    status = global_fixpoint(nodes, parents, support, {"s1", "m1"})
    assert status["m2"] == "preserved"


def test_a_revoked_status_is_not_a_root():
    """R5: the oracle's only revocation input is R. A stale `revoked` status is not modelled
    (the driver cross-checks `set(db status == revoked) == R` after every recompute)."""
    nodes = {"s1": "source", "m1": "memory", "m2": "memory"}
    parents = {"m1": ("s1",), "m2": ("m1",)}
    status = global_fixpoint(nodes, parents, {}, set())
    assert status == {"s1": "ok", "m1": "ok", "m2": "ok"}


def test_delayed_reinstate_of_a_parent_restores_children_only_when_revoked_elsewhere():
    """Two roots on one chain: removing the higher root leaves the lower root's subtree bad."""
    nodes = {"s1": "source", "m1": "memory", "m2": "memory"}
    parents = {"m1": ("s1",), "m2": ("m1",)}
    both = global_fixpoint(nodes, parents, {}, {"s1", "m1"})
    assert both == {"s1": "revoked", "m1": "revoked", "m2": "tainted"}
    after = global_fixpoint(nodes, parents, {}, {"m1"})
    assert after == {"s1": "ok", "m1": "revoked", "m2": "tainted"}


def test_never_emits_quarantined_and_reads_no_status_input():
    """R4 + the pseudocode signature: no status input, no quarantined output."""
    params = list(inspect.signature(global_fixpoint).parameters)
    assert params == ["nodes", "parents", "support", "roots"]
    nodes = {"s1": "source", "m1": "memory", "m2": "memory"}
    parents = {"m1": ("s1",), "m2": ("m1",)}
    status = global_fixpoint(nodes, parents, {}, {"s1"})
    assert set(status.values()) <= {"ok", "revoked", "preserved", "tainted"}
    assert "quarantined" not in set(status.values())


def test_illegal_models_are_rejected():
    nodes = {"s1": "source", "m1": "memory", "a1": "action"}
    with pytest.raises(AssertionError):
        global_fixpoint(nodes, {}, {}, {"a1"})  # an Action cannot be a revoked root
    with pytest.raises(AssertionError):
        global_fixpoint(nodes, {}, {}, {"ghost"})  # R must be a subset of nodes
    with pytest.raises(AssertionError):
        global_fixpoint(nodes, {}, {"a1": ("s1",)}, set())  # support keys are memories
    with pytest.raises(AssertionError):
        global_fixpoint(nodes, {}, {"m1": ("m1",)}, set())  # support targets are sources


# --- R8 drift guard: agree with evals.oracle on its valid domain ------------
@pytest.mark.parametrize("shape", [
    {"S": 4, "M": 12, "L": 2, "fan_in": 1, "p_corr": 0.0, "A": 2},
    {"S": 6, "M": 24, "L": 3, "fan_in": 2, "p_corr": 0.3, "A": 4},
    {"S": 8, "M": 40, "L": 5, "fan_in": 3, "p_corr": 0.5, "A": 6},
])
def test_drift_guard_against_the_eval_oracle(shape):
    """`evals.oracle`'s valid domain: one root, every status ok. R8's caveat (a statuses-revoked
    node outside R is treated as ok there) is deliberately not exercised: only the full R is
    ever passed, exactly as the eval calls it."""
    for seed in range(1, 201):
        dag = gen.generate(seed, **shape)
        nodes = (
            {n: "source" for n in dag.sources}
            | {n: "memory" for n in dag.memories}
            | {n: "action" for n in dag.actions}
        )
        parents = {n: tuple(ps) for n, ps in dag.parents.items()}
        support = {m: tuple(ss) for m, ss in dag.support.items()}
        roots = {dag.bad}
        mine = global_fixpoint(nodes, parents, support, roots)
        truth = truth_for_dag(dag)
        for node in dag.descendants(dag.bad):
            if node == dag.bad:
                continue
            want = ("tainted" if node in truth.G
                    else "preserved" if node in truth.should_preserve
                    else "ok")
            assert mine[node] == want, (shape, seed, node, mine[node], want)
        assert mine[dag.bad] == "revoked"


# --- mechanical independence (oracle.md section 7 item 6) -------------------
def test_oracle_module_imports_nothing_from_the_product():
    """`tests/oracle.py` must be usable as a third implementation: standard library only.
    Stronger than the review asked (no `evals` import either), so a future edit cannot turn it
    back into a re-export shim."""
    source = pathlib.Path(tests.oracle.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import in tests/oracle.py: level {node.level}"
            imported.add(node.module or "")
    assert imported <= {"__future__"}, f"tests/oracle.py imports outside the stdlib: {imported}"
