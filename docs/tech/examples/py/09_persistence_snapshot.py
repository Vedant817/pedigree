"""Persistence + demo-reset. Verifies: GRAPH.COPY snapshot/restore, server restart durability (AOF+RDB), RDB DUMP/RESTORE per graph.
Run with the local server from ../../start-falkordb.sh. The restart step needs the server's PID/launch script, so it is shell-driven (see TECH_REFERENCE)."""
import time
from common import connect, fresh_graph
db = connect(); g = fresh_graph(db, "demo_seed")
g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
g.query("UNWIND range(1,20000) AS i CREATE (:Memory {id:i, status:'valid'})")
g.query("UNWIND range(2,20000) AS i MATCH (a:Memory {id:i}),(b:Memory {id:i-1}) CREATE (a)-[:DERIVED_FROM]->(b)")
for n in ("demo_live", "demo_restore"):
    try: db.select_graph(n).delete()
    except Exception: pass
# 1. GRAPH.COPY: demo "golden" seed -> live working copy (source stays readable/writable during copy)
t = time.perf_counter(); live = g.copy("demo_live"); print(f"GRAPH.COPY seed->live (20k nodes/20k edges): {(time.perf_counter()-t)*1000:.1f} ms")
live.query("MATCH (m:Memory) WHERE m.id <= 100 SET m.status='invalidated'")
print("live invalidated:", live.ro_query("MATCH (m:Memory {status:'invalidated'}) RETURN count(m)").result_set[0][0],
      "| seed invalidated:", g.ro_query("MATCH (m:Memory {status:'invalidated'}) RETURN count(m)").result_set[0][0])
# 2. DEMO RESET = delete live + copy seed again
t = time.perf_counter(); live.delete(); live = g.copy("demo_live"); print(f"reset (delete + copy): {(time.perf_counter()-t)*1000:.1f} ms; invalidated now:",
      live.ro_query("MATCH (m:Memory {status:'invalidated'}) RETURN count(m)").result_set[0][0])
print("indexes preserved on copy:", [r[0] for r in live.ro_query("CALL db.indexes()").result_set])
# 3. DO NOT use Redis DUMP/RESTORE on a graph key: DUMP works (972 KB here) but RESTORE of that payload hit
#    "serializer_io.c: BufferSerializerIOv2_ReadUnsigned: Assertion failed" and KILLED the server (4.18.3, see bench/dump_restore_crash.txt).
#    Use GRAPH.COPY (in-server) or copy the RDB/AOF files (offline) instead.
# 4. durability markers
info = db.connection.info("persistence"); print({k: info[k] for k in ("aof_enabled", "rdb_last_bgsave_status", "rdb_saves", "aof_last_write_status")})
db.connection.save(); print("SAVE ok; last save", db.connection.lastsave())
