"""Stress: BGSAVE fork while graphs are being created/indexed/deleted. Which pattern segfaults the child?"""
import time, threading, sys
from common import connect
db = connect(); r = db.connection
r.config_set("stop-writes-on-bgsave-error", "no")
mode = sys.argv[1]
r.flushall()
stop = False
def saver():
    while not stop:
        try: r.bgsave()
        except Exception: pass
        time.sleep(0.05)
th = threading.Thread(target=saver); th.start()
t0=time.time()
try:
    for rnd in range(3):
        for i in range(300):
            g = db.select_graph(f"t{i}")
            if mode == "create_index":
                g.query("CREATE INDEX FOR (m:Memory) ON (m.id)"); g.query("CREATE (:Memory {id:'m1'})")
            elif mode == "create_only":
                g.query("CREATE (:Memory {id:'m1'})")
            elif mode == "create_delete":
                g.query("CREATE (:Memory {id:'m1'})")
        if mode in ("create_delete","create_index"):
            for i in range(300):
                try: db.select_graph(f"t{i}").delete()
                except Exception: pass
finally:
    stop = True; th.join()
time.sleep(1)
p = r.info("persistence")
print(mode, "last_status", p["rdb_last_bgsave_status"], "saves", p["rdb_saves"], "consecutive_failures", p["rdb_saves_consecutive_failures"], f"{time.time()-t0:.1f}s")
