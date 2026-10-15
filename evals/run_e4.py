"""E4 - latency and throughput on FalkorDB: revoke, blame, impact, gate (docs/03 section 1).

Seeds one throwaway graph per size through the **real** engine, then times the real engine calls
(revoke dry-run + real, blame, impact, gate) and reports p50/p95/p99 per size. Sizes are capped by
the host; the cap and the machine are recorded in the CSV (docs/03 section 3).

    python evals/run_e4.py [--sizes 1000,3000,10000] [--quick] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import uuid
from pathlib import Path

from evals import machineinfo
from evals.gen import generate, write_to_falkordb

SIZES = (1000, 3000, 10000)
QUICK_SIZES = (1000,)
ROUNDS = 5


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    ordered = sorted(values)

    def pick(q: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[index]

    return {"p50": round(pick(0.50), 2), "p95": round(pick(0.95), 2), "p99": round(pick(0.99), 2)}


def _time_call(fn, rounds: int) -> tuple[dict, list[float]]:
    samples: list[float] = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return _percentiles(samples), samples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E4 latency/throughput on FalkorDB")
    ap.add_argument("--sizes", default="")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="evals/results")
    args = ap.parse_args(argv)
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()] or (
        list(QUICK_SIZES) if args.quick else list(SIZES))
    info = machineinfo.collect()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from pedigree.config import Settings, graph_name
    from pedigree.db.client import Db
    from pedigree.db.schema import ensure_schema
    from pedigree.engine.blame import blame, impact
    from pedigree.engine.gate import check_action
    from pedigree.engine.ingest import get_node_statuses
    from pedigree.engine.revoke import revoke

    db = Db(Settings())
    rows: list[dict] = []
    for size in sizes:
        tenant = "e4" + uuid.uuid4().hex[:9]
        gname = graph_name(tenant)
        try:
            db.select(gname).delete()
        except Exception:
            pass
        ensure_schema(db, gname)
        # a chain-ish DAG of the requested order of magnitude, built through the engine
        # (total nodes ~= sources + memories + actions, so memories carry ~80% of the budget)
        memories = max(10, int(size * 0.8))
        others = max(4, size // 100)
        dag = generate(7000 + size, S=others, M=memories, L=6, fan_in=2,
                       p_corr=0.1, A=others)
        t0 = time.perf_counter()
        write_to_falkordb(db, gname, tenant, dag)
        build_ms = round((time.perf_counter() - t0) * 1000, 1)
        total = int(db.ro_query(gname, "MATCH (n) RETURN count(n)", {}).result_set[0][0])
        root = dag.bad
        anchor = next((m for m in dag.memories if root in dag.parents.get(m, [])), dag.memories[0])

        # default-arg binding makes the closures explicit for the linter (B023)
        dry, _ = _time_call(lambda r=root, g=gname, t=tenant:  # noqa: B023
                            revoke(db, g, t, root_id=r, dry_run=True), ROUNDS)
        bl, _ = _time_call(lambda a=anchor, g=gname: blame(db, g, a), ROUNDS)  # noqa: B023
        im, _ = _time_call(lambda r=root, g=gname: impact(db, g, r, max_depth=6), ROUNDS)  # noqa: B023
        gate, _ = _time_call(  # noqa: B023
            lambda a=anchor, g=gname: check_action(
                db, g, {"tool": "Bash", "summary": "git push", "effect": "irreversible",
                        "risk": "high"}, relied_on=[a], policy_path="missing-policy.yaml"), ROUNDS)
        # the real revoke is measured on a different root per round: a second revoke of the same
        # root is idempotent by design and would measure nothing.
        roots = [s for s in dag.sources if dag.descendants(s)[1:]][:ROUNDS] or [root]
        real_samples: list[float] = []
        for i in range(ROUNDS):
            target = roots[i] if i < len(roots) else root
            t0 = time.perf_counter()
            revoke(db, gname, tenant, root_id=target, reason="e4")
            real_samples.append((time.perf_counter() - t0) * 1000)
        real = _percentiles(real_samples)
        statuses = get_node_statuses(db, gname, [root])
        row = {"nodes": total, "requested": size, "build_ms": build_ms,
               "revoke_dry_p50_ms": dry["p50"], "revoke_dry_p95_ms": dry["p95"],
               "revoke_real_p50_ms": real["p50"], "revoke_real_p95_ms": real["p95"],
               "blame_p50_ms": bl["p50"], "blame_p95_ms": bl["p95"],
               "impact_p50_ms": im["p50"], "impact_p95_ms": im["p95"],
               "gate_p50_ms": gate["p50"], "gate_p95_ms": gate["p95"],
               "revoked": statuses.get(root, "?"), "rounds": ROUNDS}
        rows.append(row)
        print(f"[e4] nodes={total}: revoke(dry) p50={dry['p50']}ms p95={dry['p95']}ms | "
              f"revoke p50={real['p50']}ms p95={real['p95']}ms | blame p50={bl['p50']}ms | "
              f"impact p50={im['p50']}ms | gate p50={gate['p50']}ms")
        try:
            db.select(gname).delete()
        except Exception:
            pass

    with (out / "e4_latency.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"rounds": ROUNDS, "sizes": sizes}))
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["nodes"])
        writer.writeheader()
        writer.writerows(rows)

    numbers = _numbers(rows, info)
    (out / "numbers_e4.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    print("[e4] wrote e4_latency.csv and numbers_e4.json")
    return 0


def _numbers(rows: list[dict], info: dict) -> dict:
    out = {"e4_rounds": {"value": ROUNDS, "source": "evals/run_e4.py"},
           "e4_machine": {"value": info["os"], "source": "evals/machineinfo.py"}}
    for row in rows:
        size = row["nodes"]
        for key in ("revoke_real_p50_ms", "revoke_real_p95_ms", "blame_p50_ms",
                    "impact_p50_ms", "gate_p50_ms", "build_ms"):
            out[f"e4_{key.replace('_ms','')}_n{size}"] = {
                "value": row[key], "source": f"evals/run_e4.py ({size} nodes)"}
    return out


if __name__ == "__main__":
    sys.exit(main())
