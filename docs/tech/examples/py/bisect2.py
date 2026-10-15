import time
from common import connect
db = connect(); r = db.connection
r.config_set("stop-writes-on-bgsave-error", "no")
def try_save(label):
    before = r.info("persistence")["rdb_saves"]; r.bgsave()
    for _ in range(50):
        time.sleep(0.1); i = r.info("persistence")
        if i["rdb_bgsave_in_progress"] == 0 and i["rdb_saves"] > before: break
    print(f"{label:60s} bgsave_status={r.info('persistence')['rdb_last_bgsave_status']}")
r.flushall()
g = db.select_graph("y"); g.query("CREATE (:Memory {id:'m1'}),(:Memory {id:'m2'})"); g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
try_save("graph y: nodes + index")
r.execute_command("GRAPH.CONSTRAINT","CREATE","y","UNIQUE","NODE","Memory","PROPERTIES","1","id"); time.sleep(.5)
try_save("+ unique constraint OPERATIONAL")
g.query("CREATE (:Memory {id:'m9'})")
r.execute_command("GRAPH.CONSTRAINT","CREATE","y","MANDATORY","NODE","Memory","PROPERTIES","1","text"); time.sleep(.5)
print(g.query("CALL db.constraints()").result_set)
try_save("+ mandatory constraint in FAILED state")
r.flushall()
g = db.select_graph("tmo"); g.query("UNWIND range(1,200000) AS i CREATE (:N {i:i})")
try_save("200k node graph")
try:
    g.query("MATCH (a:N),(b:N) RETURN count(*)", timeout=200)
except Exception as e: print("timeout:", e)
try_save("after a timed-out query")
