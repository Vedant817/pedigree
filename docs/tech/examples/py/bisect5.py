"""Confirm: a *rejected* DROP INDEX on an index backing a unique constraint => next BGSAVE child segfaults (4.18.3)."""
import time, sys
from common import connect
db = connect(); r = db.connection
r.config_set("stop-writes-on-bgsave-error", "no"); r.flushall()
def save(label):
    b = r.info("persistence")["rdb_saves"]; r.bgsave()
    for _ in range(50):
        time.sleep(0.1); i = r.info("persistence")
        if i["rdb_bgsave_in_progress"] == 0 and i["rdb_saves"] > b: break
    print(f"{label:60s} {r.info('persistence')['rdb_last_bgsave_status']}")
g = db.select_graph("c1"); g.query("CREATE INDEX FOR (m:M) ON (m.id)"); g.query("CREATE (:M {id:1})")
r.execute_command("GRAPH.CONSTRAINT","CREATE","c1","UNIQUE","NODE","M","PROPERTIES","1","id"); time.sleep(.5); save("index + unique constraint")
try: g.query("DROP INDEX FOR (m:M) ON (m.id)")
except Exception as e: print("expected error:", e)
save("after rejected DROP INDEX")
r.flushall(); save("after FLUSHALL (recovery?)")
# does ordering matter: constraint WITHOUT explicit pre-created index
g = db.select_graph("c2"); g.query("CREATE (:M {id:1})")
r.execute_command("GRAPH.CONSTRAINT","CREATE","c2","UNIQUE","NODE","M","PROPERTIES","1","id"); time.sleep(.5); save("constraint w/o explicit index")
try: g.query("DROP INDEX FOR (m:M) ON (m.id)")
except Exception as e: print("expected error:", e)
save("after rejected DROP INDEX (c2)")
