import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import baselines, machineinfo, run_all, run_e1, run_e2, run_e3, run_e4, run_e4b_sqlite


def test_quick_all_writers_use_isolated_directory(tmp_path, monkeypatch):
    root = tmp_path
    results = root / "evals" / "results"
    results.mkdir(parents=True)
    published = results / "numbers.json"
    published.write_text('{"published":true}')
    monkeypatch.setattr(run_all, "ROOT", root)
    monkeypatch.setattr(run_all, "RESULTS", results)
    monkeypatch.setattr(machineinfo, "collect", lambda: {})
    seen = []

    def runner(argv):
        out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else results
        seen.append(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "numbers.json").write_text(json.dumps({"quick": True}))
        return 0

    for module in (run_e1, run_e2, run_e4, run_e4b_sqlite):
        monkeypatch.setattr(module, "main", runner)
    monkeypatch.setattr(run_e3, "main", lambda: 0)
    assert run_all.main(["--quick"]) == 0
    assert seen == [results / "quick"] * 4
    assert published.read_text() == '{"published":true}'
    assert (results / "quick" / "REPORT.md").exists()


def test_csv_keeps_intervals_and_per_metric_valid_seed_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(machineinfo, "collect", lambda: dict(os="test", cpu="test", ram_gb=1, python="test", falkor_module_version="test", commit_sha="test"))
    monkeypatch.setattr(machineinfo, "csv_header_lines", lambda *args: [])
    monkeypatch.setattr(run_e1, "calibrate_theta", lambda: (0.5, []))
    assert run_e1.main(["--quick", "--out", str(tmp_path)]) == 0
    assert run_e2.main(["--quick", "--out", str(tmp_path)]) == 0
    samples = run_all._rows(tmp_path / "e2_samples.csv")
    assert len(samples) == 8
    assert {row["seed"] for row in samples} == {str(run_e2.SEED_SPREAD), str(run_e2.SEED_SPREAD + 1)}
    for filename, metrics in (("e1_semantics.csv", ("recall", "preserved_correct")),
                              ("e2_capture.csv", ("leakage", "over_flag_ratio"))):
        rows = run_all._rows(tmp_path / filename)
        assert rows
        for metric in metrics:
            assert all(f"{metric}_{suffix}" in rows[0] for suffix in ("lo", "hi", "n_seeds"))
            assert all(int(row[f"{metric}_n_seeds"]) <= int(row["n_seeds"]) for row in rows)


def test_calibration_scores_action_union_like_e1(monkeypatch):
    monkeypatch.setattr(baselines, "b0_similarity", lambda dag, theta:
                        SimpleNamespace(pred={"memory"}, actions={"action"}))
    monkeypatch.setattr(baselines, "_truth_sets", lambda dag: {"memory", "action"})
    _, sweep = baselines.calibrate_b0_theta([object()], steps=2)
    assert sweep == [(0.0, 1.0), (1.0, 1.0)]


def test_traversal_set_check_detects_equal_size_wrong_ids():
    check = run_e4b_sqlite._assert_same_ids
    check([("a",), ("b",)], [["b"], ["a"]], "ancestors")
    with pytest.raises(AssertionError, match="ancestors"):
        check([("a",), ("b",)], [["a"], ["wrong"]], "ancestors")
