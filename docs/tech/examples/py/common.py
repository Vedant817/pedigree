"""Shared helpers. FALKOR_HOST/FALKOR_PORT/FALKOR_PASSWORD env vars; defaults localhost:6379."""
import os, time, statistics
from falkordb import FalkorDB

def connect():
    return FalkorDB(host=os.getenv("FALKOR_HOST", "localhost"),
                    port=int(os.getenv("FALKOR_PORT", "6379")),
                    password=os.getenv("FALKOR_PASSWORD") or None)

def fresh_graph(db, name):
    """Delete (if it exists) then return a handle. g.delete() on a missing key raises ResponseError."""
    try:
        db.select_graph(name).delete()
    except Exception:
        pass
    return db.select_graph(name)

def pct(xs, p):
    xs = sorted(xs); k = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[k]

def summarize(label, xs_ms):
    return (f"{label}: n={len(xs_ms)} p50={pct(xs_ms,50):.2f}ms p95={pct(xs_ms,95):.2f}ms "
            f"p99={pct(xs_ms,99):.2f}ms max={max(xs_ms):.2f}ms mean={statistics.mean(xs_ms):.2f}ms")

def wait_indexes(g, timeout=120):
    """Index builds are ASYNC. While 'UNDER CONSTRUCTION', vector queryNodes raises 'Invalid arguments for procedure'. Poll db.indexes()."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = [str(r[7]) for r in g.ro_query("CALL db.indexes()").result_set]
        if all(s.upper().startswith("OPERATIONAL") for s in st): return time.time() - t0
        time.sleep(0.1)
    raise TimeoutError("indexes not operational")
