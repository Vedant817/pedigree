"""E4b - is FalkorDB actually needed? Same closure/ancestor queries in FalkorDB (`algo.BFS`)
and in SQLite3 (stdlib, recursive CTE) on the same generated DAG (docs/03 section 1).

Scope, stated plainly: this measures the **graph traversal primitives** Pedigree depends on
(descendant closure, ancestor closure, edge read-back) - not the whole revoke pipeline. FalkorDB
also gives this implementation a per-tenant graph namespace, `GRAPH.COPY` and database ACLs.
SQLite can implement logical isolation too; this traversal benchmark does not compare isolation architectures.

    python evals/run_e4b_sqlite.py [--sizes 1000,5000] [--quick] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from evals import machineinfo
from evals.gen import generate

SIZES = (1000, 5000, 20000)
QUICK_SIZES = (1000, 5000)
ROUNDS = 3

SQL_SETUP = """
CREATE TABLE nodes (id TEXT PRIMARY KEY);
CREATE TABLE edges (parent TEXT, child TEXT);
CREATE INDEX idx_edges_parent ON edges(parent);
CREATE INDEX idx_edges_child ON edges(child);
"""

SQL_DESCENDANTS = """
WITH RECURSIVE closure(id) AS (
    SELECT :root
    UNION
    SELECT e.child FROM edges e JOIN closure c ON e.parent = c.id
)
SELECT id FROM closure WHERE id <> :root
"""

SQL_ANCESTORS = """
WITH RECURSIVE closure(id) AS (
    SELECT :root
    UNION
    SELECT e.parent FROM edges e JOIN closure c ON e.child = c.id
)
SELECT id FROM closure WHERE id <> :root
"""


def _assert_same_ids(sql_rows, graph_rows, label: str) -> int:
    sql_ids = {row[0] for row in sql_rows}
    graph_ids = {row[0] for row in graph_rows}
    assert sql_ids == graph_ids, f"{label} ID-set mismatch: sqlite-only={sorted(sql_ids - graph_ids)}; falkor-only={sorted(graph_ids - sql_ids)}"
    return len(sql_ids)


def _median_ms(fn, rounds: int) -> float:
    samples = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return samples[len(samples) // 2]


def _bulk_insert_sqlite(conn: sqlite3.Connection, dag) -> int:
    conn.executemany("INSERT INTO nodes(id) VALUES (?)", [(n,) for n in dag.created])
    edges = []
    for child, parents in dag.parents.items():
        for parent in parents:
            edges.append((parent, child))
    conn.executemany("INSERT INTO edges(parent, child) VALUES (?, ?)", edges)
    conn.commit()
    return len(edges)


def _bulk_insert_falkor(db, gname: str, dag) -> int:
    edges = [{"parent": p, "child": c} for c, ps in dag.parents.items() for p in ps]
    ids = list(dag.created)
    for start in range(0, len(ids), 2000):
        chunk = ids[start:start + 2000]
        db.query(gname, "UNWIND $ids AS i CREATE (n:Node {id:i})", {"ids": chunk}, op="e4b.nodes")
    for start in range(0, len(edges), 2000):
        chunk = edges[start:start + 2000]
        db.query(gname, """
            UNWIND $rows AS r
            MATCH (p:Node {id:r.parent}), (c:Node {id:r.child})
            MERGE (c)-[:DERIVED_FROM]->(p) MERGE (p)-[:FEEDS]->(c)
        """, {"rows": chunk}, op="e4b.edges")
    return len(edges)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="E4b FalkorDB vs SQLite traversal")
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

    db = Db(Settings())
    rows: list[dict] = []
    for size in sizes:
        memories = max(10, int(size * 0.8))
        others = max(4, size // 100)
        dag = generate(9100 + size, S=others, M=memories, L=6, fan_in=2, p_corr=0.0, A=others)

        conn = sqlite3.connect(":memory:")
        conn.executescript(SQL_SETUP)
        edges = _bulk_insert_sqlite(conn, dag)

        tenant = "e4b" + uuid.uuid4().hex[:9]
        gname = graph_name(tenant)
        try:
            db.select(gname).delete()
        except Exception:
            pass
        db._ensure_graph = None
        _bulk_insert_falkor(db, gname, dag)

        root = dag.bad
        anchor = dag.memories[-1]  # a deep memory: the ancestor query then has work to do
        sql_desc = _median_ms(lambda c=conn, r=root:  # noqa: B023
                                 c.execute(SQL_DESCENDANTS, {"root": r}).fetchall(), ROUNDS)
        sql_anc = _median_ms(lambda c=conn, r=anchor:  # noqa: B023
                                c.execute(SQL_ANCESTORS, {"root": r}).fetchall(), ROUNDS)
        graph_desc = _median_ms(
            lambda g=gname, r=root:  # noqa: B023
                db.ro_query(g, """
                MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes
                UNWIND nodes AS n RETURN n.id
            """, {"id": r, "depth": 12}, op="e4b.falkor_desc").result_set, ROUNDS)
        graph_anc = _median_ms(
            lambda g=gname, r=anchor:  # noqa: B023
                db.ro_query(g, """
                MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'DERIVED_FROM') YIELD nodes
                UNWIND nodes AS n RETURN n.id
            """, {"id": r, "depth": 12}, op="e4b.falkor_anc").result_set, ROUNDS)
        sql_n = _assert_same_ids(
            conn.execute(SQL_DESCENDANTS, {"root": root}).fetchall(),
            db.ro_query(gname, """
                MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes
                UNWIND nodes AS n RETURN n.id
            """, {"id": root, "depth": 12}, op="e4b.falkor_desc").result_set,
            "descendants")
        _assert_same_ids(
            conn.execute(SQL_ANCESTORS, {"root": anchor}).fetchall(),
            db.ro_query(gname, """
                MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'DERIVED_FROM') YIELD nodes
                UNWIND nodes AS n RETURN n.id
            """, {"id": anchor, "depth": 12}, op="e4b.falkor_anc").result_set,
            "ancestors")
        rows.append({"nodes": len(dag.created), "edges": edges,
                     "closure_sqlite_ms": round(sql_desc, 2),
                     "closure_falkor_ms": round(graph_desc, 2),
                     "ancestors_sqlite_ms": round(sql_anc, 2),
                     "ancestors_falkor_ms": round(graph_anc, 2),
                     "closure_nodes": sql_n})
        print(f"[e4b] nodes={len(dag.created)} edges={edges}: closure sqlite={sql_desc:.2f}ms "
              f"falkor={graph_desc:.2f}ms | ancestors sqlite={sql_anc:.2f}ms "
              f"falkor={graph_anc:.2f}ms | closure size={sql_n}")
        conn.close()
        try:
            db.select(gname).delete()
        except Exception:
            pass

    with (out / "e4b_falkor_vs_sqlite.csv").open("w", newline="", encoding="utf-8") as fh:
        fh.writelines(line + "\n" for line in machineinfo.csv_header_lines(
            info, {"rounds": ROUNDS, "sizes": sizes,
                   "scope": "closure + ancestor traversal primitives only"}))
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    numbers = _numbers(rows)
    (out / "numbers_e4b.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    print("[e4b] wrote e4b_falkor_vs_sqlite.csv and numbers_e4b.json")
    return 0


def _numbers(rows: list[dict]) -> dict:
    out = {}
    for row in rows:
        size = row["nodes"]
        out[f"e4b_closure_sqlite_n{size}"] = {"value": row["closure_sqlite_ms"],
                                             "source": "evals/run_e4b_sqlite.py (stdlib sqlite3)"}
        out[f"e4b_closure_falkor_n{size}"] = {"value": row["closure_falkor_ms"],
                                             "source": "evals/run_e4b_sqlite.py (algo.BFS)"}
    biggest = max(rows, key=lambda r: r["nodes"]) if rows else None
    if biggest:
        ratio = biggest["closure_sqlite_ms"] / max(0.001, biggest["closure_falkor_ms"])
        out["e4b_closure_ratio_sqlite_over_falkor_largest"] = {
            "value": round(ratio, 3),
            "source": f"evals/run_e4b_sqlite.py ({biggest['nodes']} nodes)"}
    return out


if __name__ == "__main__":
    sys.exit(main())
