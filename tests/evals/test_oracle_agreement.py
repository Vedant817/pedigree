"""The independent oracle must agree exactly with the engine's compute_final (docs/03 AT2.6),
and the in-process evaluation path must agree with the real FalkorDB revoke engine."""
from __future__ import annotations

import random

import pytest

from evals.baselines import b1_first_provenance, b2_flat, b4_full_cascade, b5_time_rewind, pedigree
from evals.gen import generate
from evals.oracle import ground_truth, truth_for_dag
from src.pedigree.engine.compute import compute_final


def _structures(dag):
    """The structures the engine reads from the graph, built from the model.

    Support is *independent* support: the poisoned root never corroborates its own descendant.
    """
    members = set(dag.descendants(dag.bad))
    parents = {n: list(dag.parents.get(n, [])) for n in members}
    support = {n: [(s, "ok") for s in dag.support.get(n, [])
                   if s in dag.sources and s != dag.bad] for n in members}
    statuses = {n: "ok" for n in members}
    return members, parents, support, statuses


def test_oracle_matches_compute_final_on_1000_random_dags():
    rng = random.Random(20261016)
    disagreements = []
    for _ in range(1000):
        seed = rng.randrange(10**9)
        dag = generate(seed, S=8, M=40, L=rng.choice([1, 2, 3, 5]), fan_in=rng.choice([1, 2, 4]),
                       p_corr=rng.choice([0.0, 0.1, 0.3]), A=6)
        members, parents, support, statuses = _structures(dag)
        final = compute_final(members, {dag.bad}, parents, support, statuses)
        truth = ground_truth(members, {dag.bad}, parents, support, statuses)
        for node in members:
            if node == dag.bad:
                continue
            engine = final.get(node)
            engine_status = engine.status if engine is not None else "ok"
            oracle_status = ("tainted" if node in truth.G else
                             "preserved" if node in truth.should_preserve else "ok")
            if engine_status != oracle_status:
                disagreements.append((seed, node, engine_status, oracle_status))
    assert not disagreements, f"{len(disagreements)} disagreements, first 5: {disagreements[:5]}"


@pytest.mark.parametrize("shape", [
    {"S": 10, "M": 60, "L": 2, "fan_in": 1, "p_corr": 0.0, "A": 8},
    {"S": 12, "M": 80, "L": 4, "fan_in": 2, "p_corr": 0.1, "A": 10},
    {"S": 12, "M": 90, "L": 6, "fan_in": 3, "p_corr": 0.3, "A": 12},
])
def test_inprocess_pedigree_matches_real_falkordb_revoke(fresh_graph, shape):
    """The eval's in-process shortcut is proven equal to the real engine, not assumed."""
    from src.pedigree.engine.ingest import get_node_statuses
    from src.pedigree.engine.revoke import revoke

    db, tenant, gname = fresh_graph
    dag = generate(1234 + shape["L"], **shape)
    from evals.gen import write_to_falkordb
    write_to_falkordb(db, gname, tenant, dag)
    revoke(db, gname, tenant, root_id=dag.bad, reason="eval")
    members, parents, support, statuses = _structures(dag)
    real = get_node_statuses(db, gname, sorted(members))
    in_process = {n: f.status for n, f in
                  compute_final(members, {dag.bad}, parents, support, statuses).items()}
    # the revoked root keeps its status in the engine and is skipped by compute_final
    assert real == {**in_process, dag.bad: "revoked"}, (
        "real FalkorDB statuses differ from the in-process predicate")


def test_b5_recall_is_one_by_construction():
    dag = generate(7, S=15, M=100, L=4, fan_in=2, p_corr=0.1, A=10)
    truth = truth_for_dag(dag)
    pred = b5_time_rewind(dag).pred
    assert truth.G <= pred


def test_b2_flags_only_direct_children():
    dag = generate(11, S=15, M=100, L=4, fan_in=2, p_corr=0.1, A=10)
    direct = {c for c, ps in dag.parents.items() if dag.bad in ps}
    assert b2_flat(dag).pred == direct


def test_b4_preserves_nothing_and_b1_keeps_shared_items():
    dag = generate(13, S=20, M=120, L=5, fan_in=2, p_corr=0.2, A=10)
    assert b4_full_cascade(dag).preserved == set()
    assert b1_first_provenance(dag).pred <= set(dag.descendants(dag.bad))
    # a memory whose first parent is NOT the bad source is not deleted by B1
    others = [m for m, ps in dag.parents.items() if ps and ps[0] != dag.bad
              and dag.bad in ps and m in dag.descendants(dag.bad)]
    if others:
        assert others[0] not in b1_first_provenance(dag).pred


def test_pedigree_preserves_independently_supported_branch():
    dag = generate(17, S=20, M=120, L=4, fan_in=2, p_corr=0.5, A=10)
    pred = pedigree(dag)
    truth = truth_for_dag(dag)
    assert pred.pred == truth.G
    assert truth.should_preserve <= pred.preserved
    for action in truth.A:
        assert action in pred.actions
