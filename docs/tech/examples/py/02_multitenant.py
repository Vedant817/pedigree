"""One graph per tenant. Verifies isolation and measures creation/query cost at N graphs."""
import sys, time, json
from common import connect, summarize
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
db = connect()
for n in db.list_graphs():
    if n.startswith("tenant_"): db.select_graph(n).delete()
rss0 = int(db.connection.info("memory")["used_memory"])
t0 = time.time(); create_ms = []
for i in range(N):
    g = db.select_graph(f"tenant_{i}")         # select_graph is lazy: nothing exists until first write
    t = time.perf_counter()
    g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
    g.query("CREATE (:Memory {id:'m1', tenant:$t})", {"t": i})
    create_ms.append((time.perf_counter() - t) * 1000)
print(f"created {N} graphs (index+1 node each) in {time.time()-t0:.2f}s")
print(summarize("create+index+node per tenant", create_ms))
rss1 = int(db.connection.info("memory")["used_memory"])
print(f"used_memory delta: {(rss1-rss0)/1024:.0f} KiB total, {(rss1-rss0)/1024/N:.1f} KiB per empty-ish tenant graph")
# isolation: a query on tenant_0 can never see tenant_1's data
a = db.select_graph("tenant_0").query("MATCH (m:Memory) RETURN m.tenant").result_set
b = db.select_graph("tenant_1").query("MATCH (m:Memory) RETURN m.tenant").result_set
assert a == [[0]] and b == [[1]], (a, b)
print("isolation OK:", a, b)
# a graph that was never written to does not exist (reading it errors or returns empty depending on call)
try:
    r = db.select_graph("tenant_never").ro_query("MATCH (n) RETURN count(n)"); print("ro_query on missing graph ->", r.result_set)
except Exception as e: print("ro_query on missing graph raises:", type(e).__name__, e)
print("list_graphs count:", len(db.list_graphs()))
# per-tenant read latency while 200 graphs exist
lat = []
for k in range(500):
    g = db.select_graph(f"tenant_{k % N}")
    t = time.perf_counter(); g.ro_query("MATCH (m:Memory {id:$i}) RETURN m", {"i": "m1"}); lat.append((time.perf_counter()-t)*1000)
print(summarize(f"indexed point read across {N} tenants (client round-trip)", lat))
# cleanup tenant (GDPR-style tenant erase) = one command
t = time.perf_counter(); db.select_graph("tenant_0").delete(); print(f"delete tenant graph: {(time.perf_counter()-t)*1000:.2f} ms")
for i in range(1, N): db.select_graph(f"tenant_{i}").delete()
