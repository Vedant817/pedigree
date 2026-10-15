"""E1 - contamination semantics: Pedigree vs B0/B1/B2/B4/B5 (docs/03 sections 1-6).

One row per (cell, system) in `evals/results/e1_semantics.csv`, one row per
(cell, seed, system) in `evals/results/e1_samples.csv`. Metrics are the docs/03 section 3
definitions; ground truth is the independent oracle in `evals/oracle.py`.

    python evals/run_e1.py [--seeds N] [--quick] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from evals import baselines, machineinfo
from evals.baselines import (
    b0_similarity,
    b1_first_provenance,
    b2_flat,
    b4_full_cascade,
    b5_time_rewind,
    pedigree,
)
from evals.gen import generate
from evals.oracle import truth_for_dag
from evals.stats import mean_ci, wilson

GRID = [(L, f, p) for L in (2, 4, 6) for f in (1, 3) for p in (0.0, 0.1, 0.3)]
QUICK_GRID = [(2, 1, 0.1)]
CALIBRATION_SEEDS = 24
FIXED = {"S": 20, "M": 200, "A": 40}
SEED_SPREAD = 1_000_003
CALIB_SEED_BASE = 900_000  # disjoint from every evaluation seed by construction


def _cell_seed(cell_index: int, seed: int) -> int:
    return (cell_index + 1) * SEED_SPREAD + seed


def _rate(k: int, n: int):
    """k/n, or None when the denominator is empty (a seed with nothing to preserve is
    skipped, not counted as a failure)."""
    return k / n if n else None


def _items_universe(dag) -> set[str]:
    """Every item a repair system could invalidate (nodes and actions)."""
    return set(dag.created)


def _score(dag, system: str, pred: set[str], preserved: set[str], actions: set[str],
           irreversible: set[str], truth) -> dict:
    universe = _items_universe(dag)
    G = truth.G
    H = universe - G
    should_preserve = truth.should_preserve
    A = truth.A
    irr_A = {a for a in A if a in dag.irreversible}
    pred_items = pred | actions
    tp = len(pred_items & G)
    recall = _rate(tp, len(G))
    fp = len(pred_items & H)
    precision = _rate(tp, tp + fp)
    f1 = _rate(2 * tp, 2 * tp + fp + max(0, len(G) - tp))
    return {
        "system": system,
        "n_g": len(G), "n_h": len(H), "n_actions": len(A), "n_irreversible": len(irr_A),
        "n_should_preserve": len(should_preserve),
        "recall": recall, "residual": None if recall is None else 1 - recall,
        "over_invalidation": _rate(fp, len(H)),
        "precision": precision, "f1": f1,
        "action_recall": _rate(len(actions & A), len(A)),
        "irreversible_recall": _rate(len(irreversible & A), len(irr_A)),
        "preserved_correct": _rate(len(preserved & should_preserve), len(should_preserve)),
    }


def _run_cell(cell_index: int, cell, seeds: int, theta: float):
    L, f, p_corr = cell
    rows = []
    for seed in range(seeds):
        dag = generate(_cell_seed(cell_index, seed), L=L, fan_in=f, p_corr=p_corr, **FIXED)
        truth = truth_for_dag(dag)
        preds = [
            ("P", pedigree(dag)),
            ("B0", b0_similarity(dag, theta)),
            ("B1", b1_first_provenance(dag)),
            ("B2", b2_flat(dag)),
            ("B4", b4_full_cascade(dag)),
            ("B5", b5_time_rewind(dag)),
        ]
        for system, prediction in preds:
            row = _score(dag, system, prediction.pred, prediction.preserved,
                         prediction.actions, prediction.irreversible, truth)
            row.update({"cell": f"L{L}-f{f}-p{p_corr}", "seed": seed})
            rows.append(row)
    return rows


def calibrate_theta() -> tuple[float, list[tuple[float, float]]]:
    """B0 theta on disjoint calibration seeds (never used for evaluation)."""
    dags = [generate(CALIB_SEED_BASE + i, **FIXED) for i in range(CALIBRATION_SEEDS)]
    return baselines.calibrate_b0_theta(dags)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E1 contamination-semantics evaluation")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--quick", action="store_true", help="2-minute subset: one cell, 2 seeds")
    ap.add_argument("--out", default="evals/results")
    args = ap.parse_args(argv)

    grid = QUICK_GRID if args.quick else GRID
    seeds = 2 if args.quick else args.seeds
    theta, sweep = calibrate_theta()
    info = machineinfo.collect()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    for idx, cell in enumerate(grid):
        rows = _run_cell(idx, cell, seeds, theta)
        all_rows.extend(rows)
        print(f"[e1] cell {rows[0]['cell']}: {len(rows)} rows")

    systems = ["P", "B0", "B1", "B2", "B4", "B5"]
    metrics = ["recall", "residual", "over_invalidation", "precision", "f1", "action_recall",
               "irreversible_recall", "preserved_correct"]

    sample_path = out / "e1_samples.csv"
    with sample_path.open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"seeds_per_cell": seeds, "b0_theta": round(theta, 4)}))
        writer = csv.DictWriter(fh, fieldnames=["cell", "seed"] + ["system"] + metrics +
                                ["n_g", "n_h", "n_actions", "n_irreversible", "n_should_preserve"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: (round(v, 6) if isinstance(v, float) else v)
                             for k, v in row.items() if k in writer.fieldnames})

    summary_path = out / "e1_semantics.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"seeds_per_cell": seeds, "b0_theta": round(theta, 4)}))
        writer = csv.DictWriter(fh, fieldnames=["cell", "system", "n_seeds"] + metrics +
                                ["n_g", "n_h", "n_actions", "n_irreversible", "n_should_preserve"])
        writer.writeheader()
        for cell_name in sorted({r["cell"] for r in all_rows}):
            for system in systems:
                cell_rows = [r for r in all_rows if r["cell"] == cell_name and r["system"] == system]
                if not cell_rows:
                    continue
                agg = {"cell": cell_name, "system": system}
                for metric in metrics:
                    values = [r[metric] for r in cell_rows if r[metric] is not None]
                    if not values:
                        agg[metric] = None
                        agg[f"{metric}_lo"] = None
                        agg[f"{metric}_hi"] = None
                        continue
                    mean, lo, hi = mean_ci(values, seed=17)
                    agg[metric] = round(mean, 6)
                    agg[f"{metric}_lo"] = round(lo, 6)
                    agg[f"{metric}_hi"] = round(hi, 6)
                agg["n_seeds"] = len(cell_rows)
                for key in ("n_g", "n_h", "n_actions", "n_irreversible", "n_should_preserve"):
                    agg[key] = sum(r[key] for r in cell_rows)
                writer.writerow({k: ("" if v is None else v) for k, v in agg.items()
                                 if k in writer.fieldnames})

    # theta sweep evidence
    with (out / "e1_b0_theta_sweep.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"calibration_seeds": CALIBRATION_SEEDS, "seed_base": CALIB_SEED_BASE}))
        writer = csv.writer(fh)
        writer.writerow(["theta", "mean_f1"])
        writer.writerows(sweep)

    numbers = _numbers(all_rows, grid, seeds, theta, info)
    (out / "numbers.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    print(f"[e1] wrote {sample_path.name}, {summary_path.name}, e1_b0_theta_sweep.csv, "
          f"numbers.json (theta={theta:.4f})")
    return 0


def _numbers(rows, grid, seeds, theta, info) -> dict:
    systems = ["P", "B0", "B1", "B2", "B4", "B5"]

    def pooled(system, metric):
        """Pool the per-seed counts over the whole grid (skipping seeds with an empty
        denominator; the Wilson interval is computed on the pooled k/n)."""
        key = {"recall": "n_g", "over_invalidation": "n_h", "action_recall": "n_actions",
               "irreversible_recall": "n_irreversible", "preserved_correct": "n_should_preserve"}
        ks, ns = [], []
        for r in rows:
            if r["system"] != system or r[metric] is None:
                continue
            ns.append(r[key[metric]])
            ks.append(round(r[metric] * ns[-1]))
        k, n = sum(ks), sum(ns)
        lo, hi = wilson(k, n)
        return {"value": round(k / n, 4) if n else 0.0, "ci95": [round(lo, 4), round(hi, 4)],
                "n": n, "source": "evals/run_e1.py"}

    out = {
        "e1_grid_cells": len(grid),
        "e1_seeds_per_cell": seeds,
        "e1_systems": len(systems),
        "e1_b0_theta": {"value": round(theta, 4), "source": "evals/run_e1.py (calibration)"},
        "e1_machine": {"value": f"{info['os']}; {info['cpu']}; {info['ram_gb']} GB RAM; "
                                f"python {info['python']}; falkor {info['falkor_module_version']}; "
                                f"commit {info['commit_sha']}",
                       "source": "evals/machineinfo.py"},
    }
    # deepest cell (L6-f3-p0.3): the number the demo/blog quote for "a cascade without support
    # check deletes too much" - reported next to the pooled value so neither is cherry-picked.
    for metric, key in (("over_invalidation", "e1_over_invalidation_b4_deepest_cell"),
                        ("recall", "e1_recall_b2_deepest_cell")):
        cell_rows = [r for r in rows if r["cell"] == "L6-f3-p0.3"
                     and r["system"] == ("B4" if "b4" in key else "B2")
                     and r[metric] is not None]
        if cell_rows:
            values = [r[metric] for r in cell_rows]
            _mean, lo, hi = mean_ci(values, seed=23)
            out[key] = {"value": round(sum(values) / len(values), 4),
                        "ci95": [round(lo, 4), round(hi, 4)],
                        "n": len(values), "source": "evals/run_e1.py (cell L6-f3-p0.3)"}
    for metric, key in (("recall", "e1_recall"), ("over_invalidation", "e1_over_invalidation"),
                        ("action_recall", "e1_action_recall"),
                        ("irreversible_recall", "e1_irreversible_recall"),
                        ("preserved_correct", "e1_preserved_correct")):
        for system in systems:
            out[f"{key}_{system.lower()}"] = pooled(system, metric)
    return out


if __name__ == "__main__":
    sys.exit(main())
