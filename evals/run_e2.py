"""E2 - capture fidelity: how missing edges (leakage) and over-approximated capture
(over-flagging) change what a repair finds (docs/03 sections 1 and 6).

Model, stated honestly in the report:
(a) precise capture drops each DERIVED_FROM edge independently with probability d;
(b) conservative read-window capture gives every node its true parents *plus* up to K
    recently-created nodes (the model of docs/01 section 7.3 "last K READ targets").

    python evals/run_e2.py [--seeds N] [--quick] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

from evals import machineinfo
from evals.gen import generate
from evals.oracle import truth_for_dag
from evals.stats import cluster_ratio_ci, mean_ci, metric_interval

DROP_RATES = (0, 1, 2, 5, 10)      # percent
WINDOWS = (5, 10, 25, 50, 100)     # K read targets
SESSIONS_PER_BUCKET = 5            # actions per modelled capture session
QUICK_DROPS = (0, 5)
QUICK_WINDOWS = (10, 50)
FIXED = {"S": 20, "M": 200, "A": 40}
SEED_SPREAD = 2_000_003


def _captured_parents(dag, rng: random.Random, drop_rate: float) -> dict[str, list[str]]:
    """(a) precise capture with a fraction of edges missing. Callers reuse one stream per
    seed so that a higher drop rate always drops a superset of the edges (monotone sweep)."""
    out: dict[str, list[str]] = {}
    for child, ps in dag.parents.items():
        kept = [p for p in ps if rng.random() * 100 >= drop_rate] if drop_rate else list(ps)
        out[child] = kept
    return out


def _window_parents(dag, k: int) -> dict[str, list[str]]:
    """(b) conservative read-window capture, modelled the way docs/01 section 7.3 describes
    it: per session the last K distinct READ targets are the influence set. Sessions bucket
    the actions (`SESSIONS_PER_BUCKET` actions each); every write/edit in a session derives
    from its true parents plus up to K carried-over reads."""
    out: dict[str, list[str]] = {}
    recent: list[str] = []          # distinct reads in the current session, oldest first
    actions_seen = 0
    session_id = -1
    for nid in dag.created:
        true = list(dag.parents.get(nid, []))
        if nid in dag.actions:
            actions_seen += 1
            bucket = (actions_seen - 1) // SESSIONS_PER_BUCKET
            if bucket != session_id:
                session_id = bucket
                recent = []
        if nid in dag.actions or nid in dag.memories:
            carried = [r for r in recent[-k:] if r not in true] if k else []
            out[nid] = true + carried
            for read in true:
                if read not in recent:
                    recent.append(read)
        else:
            out[nid] = true
    return out


def _pred_for(dag, parents: dict[str, list[str]]):
    """Pedigree semantics over a *captured* parent map (same compute_final, different input)."""
    from pedigree.engine.compute import compute_final

    captured_members = _closure(parents, dag.bad)
    support_m = {n: [(s, "ok") for s in dag.support.get(n, [])
                     if s in dag.sources and s != dag.bad] for n in captured_members}
    parents_m = {n: list(parents.get(n, [])) for n in captured_members}
    statuses_m = {n: "ok" for n in captured_members}
    final = compute_final(captured_members, {dag.bad}, parents_m, support_m, statuses_m)
    pred = {n for n, f in final.items() if f.status == "tainted"}
    preserved = {n for n, f in final.items() if f.status == "preserved"}
    actions = {a for a in dag.actions
               if any(m in pred for m in parents.get(a, []))}
    return pred, preserved, actions


def _closure(parents: dict[str, list[str]], root: str) -> set[str]:
    children: dict[str, list[str]] = {}
    for child, ps in parents.items():
        for p in ps:
            children.setdefault(p, []).append(child)
    seen = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        for kid in children.get(cur, []):
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)
    return seen


def _score(kind: str, param, dag, pred, actions, truth) -> dict:
    G = truth.G
    A = truth.A
    leaked = len(G - pred)
    extra = len(pred - G)
    extra_actions = len((actions & set(dag.actions)) - A)
    return {
        "kind": kind, "param": param,
        "recall": (1 - leaked / len(G)) if G else None,
        "leakage": leaked / len(G) if G else None,
        "over_flag_ratio": extra / len(G) if G else None,
        "extra_actions": (extra_actions / len(A)) if A else None,
        "n_g": len(G), "n_actions": len(A),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E2 capture-fidelity evaluation")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="evals/results")
    args = ap.parse_args(argv)
    drops = QUICK_DROPS if args.quick else DROP_RATES
    windows = QUICK_WINDOWS if args.quick else WINDOWS
    seeds = 2 if args.quick else args.seeds
    info = machineinfo.collect()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for seed in range(seeds):
        row_start = len(rows)
        dag = generate(SEED_SPREAD + seed, **FIXED)
        truth = truth_for_dag(dag)
        # baseline: exact capture
        pred, preserved, actions = _pred_for(dag, dict(dag.parents))
        rows.append(_score("exact", 0, dag, pred, actions, truth))
        for d in drops:
            if d == 0:
                continue
            # one draw stream per seed, thresholded: a higher drop rate drops a superset of
            # the edges a lower rate drops, so the sweep is monotone by construction
            rng = random.Random(SEED_SPREAD + seed * 1000)
            parents = _captured_parents(dag, rng, d)
            pred, preserved, actions = _pred_for(dag, parents)
            rows.append(_score("edge_drop", d, dag, pred, actions, truth))
        for k in windows:
            parents = _window_parents(dag, k)
            pred, preserved, actions = _pred_for(dag, parents)
            rows.append(_score("window", k, dag, pred, actions, truth))
        for row in rows[row_start:]:
            row["seed"] = SEED_SPREAD + seed
    print(f"[e2] {len(rows)} rows over {seeds} seeds")

    metrics = ["recall", "leakage", "over_flag_ratio", "extra_actions"]
    with (out / "e2_samples.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"seeds": seeds, "drop_rates": list(drops), "windows": list(windows)}))
        writer = csv.DictWriter(fh, fieldnames=["seed", "kind", "param"] + metrics + ["n_g", "n_actions"])
        writer.writeheader()
        writer.writerows(rows)
    with (out / "e2_capture.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"seeds": seeds, "drop_rates": list(drops), "windows": list(windows)}))
        writer = csv.DictWriter(fh, fieldnames=["kind", "param", "n_seeds", "ci_method"] +
                                [name for metric in metrics for name in (metric, f"{metric}_lo", f"{metric}_hi", f"{metric}_n_seeds")] + ["n_g", "n_actions"])
        writer.writeheader()
        for kind in ("exact", "edge_drop", "window"):
            for param in sorted({r["param"] for r in rows if r["kind"] == kind}):
                subset = [r for r in rows if r["kind"] == kind and r["param"] == param]
                agg: dict = {"kind": kind, "param": param, "n_seeds": len(subset),
                             "ci_method": "seed bootstrap percentile 95%; 10000 resamples"}
                for metric in metrics:
                    values = [r[metric] for r in subset if r[metric] is not None]
                    agg[f"{metric}_n_seeds"] = len(values)
                    if not values:
                        agg[f"{metric}_lo"] = agg[f"{metric}_hi"] = None
                        agg[metric] = None
                        continue
                    mean, lo, hi = mean_ci(values, seed=19)
                    agg[metric] = round(mean, 6)
                    agg[f"{metric}_lo"] = round(lo, 6)
                    agg[f"{metric}_hi"] = round(hi, 6)
                agg["n_g"] = sum(r["n_g"] for r in subset)
                agg["n_actions"] = sum(r["n_actions"] for r in subset)
                writer.writerow({k: ("" if v is None else v) for k, v in agg.items()
                                 if k in writer.fieldnames})

    numbers = _numbers(rows)
    (out / "numbers_e2.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    print("[e2] wrote e2_samples.csv, e2_capture.csv and numbers_e2.json")
    return 0


# Proper proportions use pooled counts; unbounded ratios retain the per-seed mean.
PROPORTIONS = ("recall", "leakage")


def _pooled(rows, kind, param, metric, count_key) -> dict:
    total = [r for r in rows if r["kind"] == kind and r["param"] == param]
    subset = [r for r in total if r[metric] is not None]
    n = sum(r[count_key] for r in subset)
    method = "seed-cluster bootstrap percentile 95%; 10000 resamples"
    if not subset:
        value = lo = hi = None
    elif metric not in PROPORTIONS:
        value, lo, hi = mean_ci([r[metric] for r in subset], seed=19)
        method = "seed-mean bootstrap percentile 95%; 10000 resamples"
    else:
        pairs = [(round(r[metric] * r[count_key]), r[count_key])
                 if r[metric] is not None else (0, 0) for r in total]
        value, lo, hi = cluster_ratio_ci([pairs], seed=19)
    return metric_interval(value, lo, hi, n_clusters=len(subset), n_items=n,
                           n_total=len(total), method=method, source="evals/run_e2.py")


def _numbers(rows) -> dict:
    out = {}
    for d in DROP_RATES:
        if d == 0:
            continue
        out[f"e2_leakage_edge_drop_{d}pct"] = _pooled(rows, "edge_drop", d, "leakage", "n_g")
    for k in WINDOWS:
        out[f"e2_window_over_flag_k{k}"] = _pooled(rows, "window", k, "over_flag_ratio", "n_g")
        out[f"e2_window_extra_actions_k{k}"] = _pooled(rows, "window", k, "extra_actions",
                                                       "n_actions")
    out["e2_exact_leakage"] = _pooled(rows, "exact", 0, "leakage", "n_g")
    return out


if __name__ == "__main__":
    sys.exit(main())
