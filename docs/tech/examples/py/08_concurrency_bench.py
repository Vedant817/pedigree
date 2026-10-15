"""Concurrency: parallel readers scaling, reads during a long write, concurrent writers serialisation. Uses graph scale_dense (run 10_scale_bench.py dense first)."""
import threading, time, random, sys
from common import connect, summarize, pct
GRAPH = sys.argv[1] if len(sys.argv) > 1 else "scale_dense"
READ = "MATCH (s:Source {id:$s}) CALL algo.BFS(s,3,'FEEDS') YIELD nodes RETURN size(nodes)"   # cheap-ish read
def worker(n_ops, lat, seed, stop=None):
    db = connect(); g = db.select_graph(GRAPH); rnd = random.Random(seed)
    for _ in range(n_ops):
        if stop and stop.is_set(): break
        t = time.perf_counter(); g.ro_query(READ, {"s": rnd.randrange(1000)}); lat.append((time.perf_counter() - t) * 1000)
for nthreads in (1, 2, 4, 8, 16):
    lats = [[] for _ in range(nthreads)]; per = 400
    ths = [threading.Thread(target=worker, args=(per, lats[i], i)) for i in range(nthreads)]
    t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
    allv = [x for l in lats for x in l]
    print(f"readers={nthreads:2d}: {len(allv)/dt:8.0f} queries/s  " + summarize("lat", allv))
# readers while a long write runs (cascade write ~500ms on dense graph), 4 readers
db = connect(); g = db.select_graph(GRAPH)
stop = threading.Event(); lat = [[] for _ in range(4)]
ths = [threading.Thread(target=worker, args=(10**6, lat[i], 100 + i, stop)) for i in range(4)]
[t.start() for t in ths]; time.sleep(1.0)
base = [x for l in lat for x in l]; [l.clear() for l in lat]
wlat = []
for s in range(5):
    t = time.perf_counter()
    g.query("""MATCH (s:Source {id:$s}) SET s.status='retracted' WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m SET m.status='invalidated' RETURN count(m)""", {"s": s})
    wlat.append((time.perf_counter() - t) * 1000)
    g.query("MATCH (n) WHERE n.status IN ['invalidated','retracted'] SET n.status = CASE WHEN n:Source THEN 'active' ELSE 'valid' END")
during = [x for l in lat for x in l]; stop.set(); [t.join() for t in ths]
print(summarize("reader latency BEFORE writes", base)); print(summarize("reader latency DURING cascade writes", during)); print(summarize("cascade write latency (with 4 readers hammering)", wlat))
# concurrent writers on the SAME graph: serialised
def writer(i, out):
    d = connect(); gg = d.select_graph("conc_w")
    for k in range(200):
        t = time.perf_counter(); gg.query("CREATE (:W {w:$w,k:$k})", {"w": i, "k": k}); out.append((time.perf_counter() - t) * 1000)
db.select_graph("conc_w").query("CREATE (:Init)")
for nthreads in (1, 4, 8):
    outs = [[] for _ in range(nthreads)]; ths = [threading.Thread(target=writer, args=(i, outs[i])) for i in range(nthreads)]
    t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
    allv = [x for o in outs for x in o]; print(f"writers={nthreads}: {len(allv)/dt:7.0f} writes/s  " + summarize("lat", allv))
# writers on DIFFERENT graphs (tenants) in parallel
def writer2(i, out):
    d = connect(); gg = d.select_graph(f"conc_t{i}")
    for k in range(200):
        t = time.perf_counter(); gg.query("CREATE (:W {w:$w,k:$k})", {"w": i, "k": k}); out.append((time.perf_counter() - t) * 1000)
for nthreads in (4, 8):
    outs = [[] for _ in range(nthreads)]; ths = [threading.Thread(target=writer2, args=(i, outs[i])) for i in range(nthreads)]
    t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
    allv = [x for o in outs for x in o]; print(f"writers on {nthreads} different graphs: {len(allv)/dt:7.0f} writes/s  " + summarize("lat", allv))
for i in range(8): 
    try: db.select_graph(f"conc_t{i}").delete()
    except Exception: pass
db.select_graph("conc_w").delete()
