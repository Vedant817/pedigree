"""Server RSS for 100k nodes + 500k edges (single DERIVED_FROM type, uniform parents, 3 props/node) and per-tenant overhead. Run against a FRESH server (flushall first)."""
import random, time
from common import connect, wait_indexes
db = connect(); r = db.connection; r.flushall(); time.sleep(1)
def rss(): 
    i = r.info("memory"); return int(i["used_memory_rss"]) / 1048576, int(i["used_memory"]) / 1048576
print("empty server: rss=%.0f MiB used_memory=%.0f MiB" % rss())
g = db.select_graph("mem100k"); g.query("CREATE INDEX FOR (n:Memory) ON (n.id)")
N, E = 100000, 500000; random.seed(3)
for k in range(0, N, 20000):
    g.query("UNWIND range($a,$b) AS i CREATE (:Memory {id:i, status:'valid', text:'memory number ' + toString(i)})", {"a": k, "b": k + 19999})
print("after 100k nodes: rss=%.0f MiB used_memory=%.0f MiB" % rss())
rows = [[random.randrange(1, N), 0] for _ in range(E)]
rows = [[a, random.randrange(0, a)] for a, _ in rows]            # DAG: child id > parent id
for k in range(0, E, 25000):
    g.query("UNWIND $r AS x MATCH (a:Memory {id:x[0]}),(b:Memory {id:x[1]}) CREATE (a)-[:DERIVED_FROM {w:1.0}]->(b)", {"r": rows[k:k + 25000]})
wait_indexes(g); time.sleep(1)
print("after 500k edges (1 prop each): rss=%.0f MiB used_memory=%.0f MiB" % rss())
print("GRAPH.MEMORY USAGE:", r.execute_command("GRAPH.MEMORY", "USAGE", "mem100k"))
g.delete(); time.sleep(2); print("after delete graph: rss=%.0f MiB used_memory=%.0f MiB (RSS may not shrink: allocator)" % rss())
r.flushall(); time.sleep(1)
base = rss()
for i in range(1000):
    t = db.select_graph(f"tn_{i}"); t.query("CREATE INDEX FOR (m:Memory) ON (m.id)"); t.query("CREATE (:Memory {id:1})")
print("1000 tenant graphs (1 index + 1 node each): rss delta=%.0f MiB used_memory delta=%.0f MiB" % (rss()[0] - base[0], rss()[1] - base[1]))
t0 = time.perf_counter(); [db.select_graph(f"tn_{i}").ro_query("MATCH (m:Memory {id:1}) RETURN m") for i in range(1000)]; print("1000 point reads across 1000 tenants: %.2f ms avg" % ((time.perf_counter() - t0)))
for i in range(1000): db.select_graph(f"tn_{i}").delete()
