"""Cascade-invalidate benchmark: 100k nodes / ~500k DERIVED_FROM edges (+ mirrored FEEDS edges), depth 10.
usage: python 10_scale_bench.py dense|local [n_seeds]
 dense : each memory has 5 parents chosen UNIFORMLY from the previous level  (worst case: reachability explodes, exponential path count)
 local : 5 parents chosen from a +-WINDOW neighbourhood of the previous level (clustered provenance, closer to real agent memory)
Edge model (both written for every provenance link):
   (child)-[:DERIVED_FROM]->(parent)   # answers "why / where did this come from?"  (walk with algo.BFS from child)
   (parent)-[:FEEDS]->(child)          # answers "what is affected?"                (walk with algo.BFS from source)
 because algo.BFS only follows OUTGOING edges of ONE type.
"""
import sys, time, random, json
from common import connect, fresh_graph, summarize, wait_indexes, pct
topo = sys.argv[1] if len(sys.argv) > 1 else "dense"
SEEDS = int(sys.argv[2]) if len(sys.argv) > 2 else 30
NS, LV, W, PAR = 1000, 10, 9900, 5          # 1000 sources + 10 levels x 9900 memories = 100,000 nodes; 5 parents => ~495k edges
WINDOW = 60
random.seed(7)
db = connect(); g = fresh_graph(db, f"scale_{topo}")
rss0 = int(db.connection.info("memory")["used_memory"])
g.query("CREATE INDEX FOR (n:Source) ON (n.id)"); g.query("CREATE INDEX FOR (n:Memory) ON (n.id)"); g.query("CREATE INDEX FOR (n:Decision) ON (n.id)")
t0 = time.time()
g.query("UNWIND range(0,$n-1) AS i CREATE (:Source {id:i, status:'active', trust:0.5})", {"n": NS})
for l in range(1, LV + 1):
    g.query("UNWIND range(0,$n-1) AS i CREATE (:Memory {id:$base + i, level:$l, status:'valid'})", {"n": W, "base": l * 100000, "l": l})
def parents(l, i):
    size = NS if l == 1 else W
    if topo == "dense":
        return random.sample(range(size), PAR)
    centre = int(i * size / W); lo = max(0, centre - WINDOW); hi = min(size, centre + WINDOW)
    return random.sample(range(lo, hi), PAR)
nedges = 0
for l in range(1, LV + 1):
    rows = []
    for i in range(W):
        for p in parents(l, i):
            rows.append([l * 100000 + i, (p if l == 1 else (l - 1) * 100000 + p)])
    nedges += len(rows)
    lab = "Source" if l == 1 else "Memory"
    for k in range(0, len(rows), 20000):
        g.query(f"UNWIND $rows AS r MATCH (c:Memory {{id:r[0]}}),(p:{lab} {{id:r[1]}}) CREATE (c)-[:DERIVED_FROM]->(p), (p)-[:FEEDS]->(c)", {"rows": rows[k:k+20000]})
# 5,000 decisions each depending on 3 random memories from levels 8-10
drows = [[i, [random.choice(range(8, 11)) * 100000 + random.randrange(W) for _ in range(3)]] for i in range(5000)]
g.query("UNWIND $r AS d CREATE (x:Decision {id:d[0]}) WITH x, d UNWIND d[1] AS mid MATCH (m:Memory {id:mid}) CREATE (x)-[:DEPENDS_ON]->(m)", {"r": drows})
ing = time.time() - t0
wait_indexes(g)
print(f"[{topo}] ingest {ing:.1f}s: nodes={g.ro_query('MATCH (n) RETURN count(n)').result_set[0][0]} DERIVED_FROM={g.ro_query('MATCH ()-[e:DERIVED_FROM]->() RETURN count(e)').result_set[0][0]} FEEDS={g.ro_query('MATCH ()-[e:FEEDS]->() RETURN count(e)').result_set[0][0]} DEPENDS_ON={g.ro_query('MATCH ()-[e:DEPENDS_ON]->() RETURN count(e)').result_set[0][0]}")
rss1 = int(db.connection.info("memory")["used_memory"])
print(f"[{topo}] server used_memory delta: {(rss1-rss0)/1048576:.0f} MiB; GRAPH.MEMORY USAGE: {db.connection.execute_command('GRAPH.MEMORY','USAGE',f'scale_{topo}')}")

seeds = random.sample(range(NS), SEEDS)
def timed(q, p, timeout=15000, ro=True):
    t = time.perf_counter()
    try:
        r = (g.ro_query if ro else g.query)(q, p, timeout=timeout)
        return (time.perf_counter() - t) * 1000, r.result_set, None
    except Exception as e:
        return (time.perf_counter() - t) * 1000, None, str(e)

results = {"topology": topo, "nodes": 100000, "edges_derived_from": nedges}
# 1. Impact preview via algo.BFS over FEEDS (read-only), depth unbounded and depth 10
for label, depth in (("bfs_depth10", 10),):
    lat, sizes = [], []
    for s in seeds:
        ms, rs, err = timed("MATCH (s:Source {id:$s}) CALL algo.BFS(s,$d,'FEEDS') YIELD nodes RETURN size(nodes)", {"s": s, "d": depth})
        lat.append(ms); sizes.append(rs[0][0])
    print(summarize(f"[{topo}] preview via algo.BFS FEEDS depth10", lat), f"| affected nodes: p50={pct(sizes,50)} p95={pct(sizes,95)} max={max(sizes)}")
    results[label] = {"p50_ms": pct(lat,50), "p95_ms": pct(lat,95), "affected_p50": pct(sizes,50), "affected_p95": pct(sizes,95), "affected_max": max(sizes)}
# 2. Cascade WRITE via BFS (single atomic query), then reset (not timed)
lat, aff = [], []
for s in seeds:
    ms, rs, err = timed("""MATCH (s:Source {id:$s}) SET s.status='retracted'
        WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m SET m.status='invalidated', m.by=s.id RETURN count(m)""", {"s": s}, ro=False)
    lat.append(ms); aff.append(rs[0][0])
    g.query("MATCH (n) WHERE n.status IN ['invalidated','retracted'] SET n.status = CASE WHEN n:Source THEN 'active' ELSE 'valid' END")
print(summarize(f"[{topo}] CASCADE WRITE via BFS (atomic, 1 query)", lat), f"| invalidated p50={pct(aff,50)} max={max(aff)}")
results["cascade_write_bfs"] = {"p50_ms": pct(lat,50), "p95_ms": pct(lat,95), "affected_p50": pct(aff,50), "affected_max": max(aff)}
# 3. Dependent decisions after cascade (BFS then join to Decision)
lat, nd = [], []
for s in seeds:
    ms, rs, err = timed("""MATCH (s:Source {id:$s}) CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m
        MATCH (m)<-[:DEPENDS_ON]-(d:Decision) RETURN count(DISTINCT d)""", {"s": s})
    lat.append(ms); nd.append(rs[0][0])
print(summarize(f"[{topo}] dependent Decisions via BFS + join", lat), f"| decisions p50={pct(nd,50)} max={max(nd)}")
results["dependents_bfs"] = {"p50_ms": pct(lat,50), "p95_ms": pct(lat,95), "decisions_p50": pct(nd,50), "decisions_max": max(nd)}
# 4. Variable-length path (path ENUMERATION) with depth sweep on a single seed: shows exponential blowup / timeouts
sweep = {}
for k in (2, 3, 4, 5, 6, 8, 10):
    ms, rs, err = timed(f"MATCH (s:Source {{id:$s}})-[:FEEDS*1..{k}]->(m:Memory) RETURN count(DISTINCT m)", {"s": seeds[0]}, timeout=10000)
    sweep[k] = {"ms": round(ms, 1), "distinct": rs[0][0] if rs else None, "error": err}
    print(f"[{topo}] var-length FEEDS*1..{k}: {ms:8.1f} ms  distinct={rs[0][0] if rs else None} {err or ''}")
results["varlen_sweep_seed0"] = sweep
# 5. 'Why' query: ancestors of a deep memory via BFS over DERIVED_FROM
lat, anc = [], []
for i in range(SEEDS):
    mid = 10 * 100000 + random.randrange(W)
    ms, rs, err = timed("MATCH (m:Memory {id:$m}) CALL algo.BFS(m,10,'DERIVED_FROM') YIELD nodes RETURN size(nodes), size([n IN nodes WHERE n:Source])", {"m": mid})
    lat.append(ms); anc.append(rs[0][0])
print(summarize(f"[{topo}] ancestors of level-10 memory via BFS DERIVED_FROM", lat), f"| ancestors p50={pct(anc,50)}")
results["ancestors_bfs"] = {"p50_ms": pct(lat,50), "p95_ms": pct(lat,95), "ancestors_p50": pct(anc,50)}
# 6. Wave (set-based frontier) cascade in pure Cypher: one query per level, WHERE status='valid' acts as visited-set, prunes already-invalid
lat = []; tot = []
for s in seeds[:10]:
    t = time.perf_counter(); n = 0
    g.query("MATCH (s:Source {id:$s}) SET s.status='retracted', s.wave=0", {"s": s})
    r = g.query("MATCH (s:Source {id:$s})-[:FEEDS]->(m:Memory {status:'valid'}) SET m.status='invalidated', m.wave=1 RETURN count(DISTINCT m)", {"s": s}); n += r.result_set[0][0]
    for w in range(1, 10):
        r = g.query("MATCH (p:Memory {wave:$w, status:'invalidated'})-[:FEEDS]->(m:Memory {status:'valid'}) SET m.status='invalidated', m.wave=$w+1 RETURN count(DISTINCT m)", {"w": w}); c = r.result_set[0][0]
        n += c
        if c == 0: break
    lat.append((time.perf_counter() - t) * 1000); tot.append(n)
    g.query("MATCH (n) WHERE n.status IN ['invalidated','retracted'] SET n.status = CASE WHEN n:Source THEN 'active' ELSE 'valid' END REMOVE n.wave")
print(summarize(f"[{topo}] wave cascade (<=10 queries, NOT atomic overall; label-scan on wave property)", lat), f"| invalidated p50={pct(tot,50)}")
results["wave_cascade"] = {"p50_ms": pct(lat,50), "p95_ms": pct(lat,95), "invalidated_p50": pct(tot,50)}
json.dump(results, open(f"../../bench/scale_{topo}.json", "w"), indent=1)
