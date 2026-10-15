"""Reproduce the schema-save segfault: replay y-graph sequence step by step, BGSAVE after each step."""
import time
from common import connect
db = connect(); r = db.connection
r.config_set("stop-writes-on-bgsave-error", "no"); r.flushall()
def save(label):
    b = r.info("persistence")["rdb_saves"]; r.bgsave()
    for _ in range(50):
        time.sleep(0.1); i = r.info("persistence")
        if i["rdb_bgsave_in_progress"] == 0 and i["rdb_saves"] > b: break
    print(f"{label:60s} {r.info('persistence')['rdb_last_bgsave_status']}")
g = db.select_graph("y")
g.query("CREATE (:Memory {id:'m1', text:'hello', emb: vecf32([0.1,0.2,0.3,0.4])}), (:Memory {id:'m2', text:'prov', emb: vecf32([0.9,0.1,0.0,0.0])})"); save("nodes with vec prop")
g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
g.query("CREATE INDEX FOR ()-[r:DERIVED_FROM]-() ON (r.w)"); save("range idx node + rel idx (no edges of that type)")
g.query("CREATE FULLTEXT INDEX FOR (m:Memory) ON (m.text)")
g.query("CREATE VECTOR INDEX FOR (m:Memory) ON (m.emb) OPTIONS {dimension:4, similarityFunction:'cosine'}"); save("+fulltext+vector")
r.execute_command("GRAPH.CONSTRAINT","CREATE","y","UNIQUE","NODE","Memory","PROPERTIES","1","id"); time.sleep(.5); save("+unique constraint")
r.execute_command("GRAPH.CONSTRAINT","CREATE","y","MANDATORY","NODE","Memory","PROPERTIES","1","text"); time.sleep(.5); save("+mandatory (async, may fail)")
try: g.query("DROP INDEX FOR (m:Memory) ON (m.id)")
except Exception as e: print("drop index err:", e)
save("after failed DROP INDEX")
g2 = db.select_graph("x")
g2.query("CREATE (:M {id:'a'})-[:DERIVED_FROM]->(:M {id:'b'})"); g2.query("MATCH (m:M {id:'a'}) SET m.n=[[1],[2]]"); save("graph x with nested-list property")
g2.query("MATCH (m:M {id:'a'}) SET m.n=[1,'a',2.5]"); save("graph x mixed-type list")
db.select_graph("t").query("RETURN 1"); save("graph t created by RETURN 1 only (empty key?)")
print(r.execute_command("GRAPH.LIST"))
