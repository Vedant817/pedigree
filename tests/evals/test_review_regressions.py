"""Independent bounded statistical-review checks; never regenerate published artifacts."""
from __future__ import annotations

import random

from evals.baselines import b0_similarity, calibrate_b0_theta
from evals.gen import Dag, generate
from evals.run_e1 import CALIB_SEED_BASE, CALIBRATION_SEEDS, GRID, _cell_seed
from evals.run_e2 import DROP_RATES, _captured_parents


def test_b0_uses_text_similarity_rather_than_graph_reachability():
    dag = Dag(seed=1, params={}, sources=["bad", "unrelated"], memories=["child"],
              created=["bad", "unrelated", "child"], bad="bad",
              parents={"child": ["bad"]},
              texts={"bad": "same words", "unrelated": "same words", "child": "other tokens"})
    prediction = b0_similarity(dag, 0.99)
    assert prediction.pred == {"unrelated"}


def test_b0_calibration_sweep_evaluates_every_declared_threshold():
    dags = [generate(900_000 + i, S=4, M=12, A=2, L=2) for i in range(2)]
    theta, sweep = calibrate_b0_theta(dags, steps=5)
    assert [point for point, _ in sweep] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert theta == max(sweep, key=lambda point: point[1])[0]


def test_b0_calibration_scores_the_same_action_union_as_e1(monkeypatch):
    from evals import baselines

    def prediction(_dag, theta):
        if theta == 0:
            return baselines.Prediction("B0", pred={"a"}, actions={"b"})
        return baselines.Prediction("B0", pred={"a", "b"}, actions={"c", "d"})

    monkeypatch.setattr(baselines, "b0_similarity", prediction)
    monkeypatch.setattr(baselines, "_truth_sets", lambda _dag: {"a", "b"})
    theta, sweep = baselines.calibrate_b0_theta([object()], steps=2)
    assert theta == 0
    assert sweep == [(0.0, 1.0), (1.0, 0.6667)]


def test_default_grid_calibration_seeds_are_disjoint_from_evaluation():
    calibration = {CALIB_SEED_BASE + i for i in range(CALIBRATION_SEEDS)}
    evaluation = {_cell_seed(cell, seed) for cell in range(len(GRID)) for seed in range(30)}
    assert len(evaluation) == 540
    assert calibration.isdisjoint(evaluation)


def test_e2_edge_drop_is_nested_under_identical_per_seed_draws():
    for seed in (2_000_003, 2_000_004, 2_000_005):
        dag = generate(seed, S=8, M=50, A=8, L=4)
        previous = set()
        all_edges = {(child, parent) for child, ps in dag.parents.items() for parent in ps}
        for rate in DROP_RATES:
            captured = _captured_parents(dag, random.Random(seed), rate)
            kept = {(child, parent) for child, ps in captured.items() for parent in ps}
            dropped = all_edges - kept
            assert previous <= dropped
            previous = dropped
