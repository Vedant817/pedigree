"""Bisect which graph feature makes BGSAVE (fork child) segfault on falkordb 4.18.3 (falkordblite 0.10.0 wheel)."""
import time, sys
from common import connect
db = connect(); r = db.connection
def try_save(label):
    before = r.info("persistence")["rdb_saves"]
    r.bgsave()
    for _ in range(50):
        time.sleep(0.1)
        i = r.info("persistence")
        if i["rdb_bgsave_in_progress"] == 0 and i["rdb_saves"] > before: break
    print(f"{label:55s} bgsave_status={r.info('persistence')['rdb_last_bgsave_status']}")
def reset():
    r.flushall()
r.config_set("stop-writes-on-bgsave-error", "no")
reset(); try_save("empty db")
g = db.select_graph("a"); g.query("CREATE (:M {id:1})-[:R]->(:M {id:2})"); try_save("plain graph, 2 nodes 1 edge")
g.query("CREATE INDEX FOR (m:M) ON (m.id)"); try_save("+ range index")
g.query("CREATE FULLTEXT INDEX FOR (m:M) ON (m.t)"); try_save("+ fulltext index")
g.query("CREATE (:M {id:3, e: vecf32([1,2,3,4])})"); g.query("CREATE VECTOR INDEX FOR (m:M) ON (m.e) OPTIONS {dimension:4, similarityFunction:'cosine'}"); try_save("+ vector index")
reset(); g = db.select_graph("b"); g.query("CREATE (:M {id:1})"); g.query("CREATE INDEX FOR (m:M) ON (m.id)")
r.execute_command("GRAPH.CONSTRAINT","CREATE","b","UNIQUE","NODE","M","PROPERTIES","1","id"); time.sleep(.5); try_save("graph + unique constraint")
reset(); g = db.select_graph("c"); g.query("CREATE (:M {id:1})"); g.query("CREATE INDEX FOR ()-[e:R]-() ON (e.w)"); try_save("graph + relationship index (0 edges)")
reset(); g = db.select_graph("d"); g.query("CREATE INDEX FOR (m:M) ON (m.id)"); try_save("graph with only an index (0 nodes)")
reset(); 
for i in range(300): db.select_graph(f"t{i}").query("CREATE (:M {id:1})")
try_save("300 tiny graphs")
reset()
for i in range(300):
    g = db.select_graph(f"t{i}"); g.query("CREATE INDEX FOR (m:M) ON (m.id)"); g.query("CREATE (:M {id:1})")
try_save("300 tiny graphs each with index")
