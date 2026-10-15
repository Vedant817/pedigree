"""Do reads on the SAME graph block while a long write runs? Do reads on OTHER graphs? (scale_dense must exist)"""
import threading, time
from common import connect, summarize
db = connect(); other = db.select_graph("tenant_smoke")
def reader(graph, out, stop):
    d = connect(); g = d.select_graph(graph)
    while not stop.is_set():
        t = time.perf_counter(); g.ro_query("MATCH (n) RETURN count(n) LIMIT 1" if graph != "scale_dense" else "MATCH (s:Source {id:5}) RETURN s.id"); out.append((time.time(), (time.perf_counter()-t)*1000))
        time.sleep(0.002)
for graph in ("scale_dense", "tenant_smoke"):
    out = []; stop = threading.Event(); th = threading.Thread(target=reader, args=(graph, out, stop)); th.start(); time.sleep(0.5)
    g = db.select_graph("scale_dense"); t0 = time.time()
    g.query("MATCH (s:Source {id:3}) SET s.status='retracted' WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m SET m.status='invalidated' RETURN count(m)")
    t1 = time.time(); time.sleep(0.3); stop.set(); th.join()
    g.query("MATCH (n) WHERE n.status IN ['invalidated','retracted'] SET n.status = CASE WHEN n:Source THEN 'active' ELSE 'valid' END")
    during = [l for ts, l in out if t0 <= ts <= t1 + 0.05]; before = [l for ts, l in out if ts < t0]
    print(f"reader on {graph:13s}: write took {(t1-t0)*1000:.0f} ms | " + summarize("before", before) + " | " + summarize("during", during or [0]))
