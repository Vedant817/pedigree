from evals.run_e1 import _numbers
from evals.run_e2 import _pooled
from evals.stats import cluster_ratio_ci


def test_e1_cluster_ci_uses_dags_and_null_for_empty_denominators():
    rows = []
    for seed, (hits, n) in enumerate(((0, 100), (100, 100))):
        rows.append(dict(cell="a", seed=seed, system="P", recall=hits / n,
                         n_g=n, over_invalidation=None, action_recall=None,
                         irreversible_recall=None, preserved_correct=None))
    info = dict(os="x", cpu="x", ram_gb=1, python="x", falkor_module_version="x", commit_sha="x")
    result = _numbers(rows, ["a"], 2, 0.5, info)
    recall = result["e1_recall_p"]
    assert recall["value"] == 0.5
    assert recall["ci95"] == [0.0, 1.0]
    assert recall["n_clusters"] == 2 and recall["n_items"] == 200
    assert "stratified" in recall["ci_method"]
    assert result["e1_action_recall_p"]["value"] is None
    assert result["e1_action_recall_p"]["ci95"] is None


def test_e2_ratio_n_is_seed_count_and_items_are_separate():
    rows = [dict(kind="window", param=5, over_flag_ratio=v, n_g=100) for v in (0, 2)]
    result = _pooled(rows, "window", 5, "over_flag_ratio", "n_g")
    assert result["n"] == result["n_clusters"] == 2
    assert result["n_items"] == 200
    assert result["ci95"] == [0.0, 2.0]


def test_e2_proportions_use_cluster_uncertainty():
    rows = [dict(kind="exact", param=0, leakage=v, n_g=100) for v in (0, 1)]
    result = _pooled(rows, "exact", 0, "leakage", "n_g")
    assert result["value"] == 0.5 and result["ci95"] == [0.0, 1.0]


def test_stratified_bootstrap_keeps_fixed_cell_composition_and_pooled_point():
    assert cluster_ratio_ci([[(0, 100)] * 2, [(10, 10)] * 2]) == (1 / 11, 1 / 11, 1 / 11)
    assert cluster_ratio_ci([[(0, 0)]]) == (None, None, None)
    assert cluster_ratio_ci([[(0, 100), (5, 5)]], seed=7) == cluster_ratio_ci(
        [[(0, 100), (5, 5)]], seed=7)
