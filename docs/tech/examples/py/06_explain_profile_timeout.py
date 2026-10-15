"""GRAPH.EXPLAIN / PROFILE, per-query timeout, server timeout config, GRAPH.SLOWLOG, GRAPH.MEMORY."""
from common import connect, fresh_graph
from falkordb import FalkorDB
db = connect(); g = fresh_graph(db, "demo_explain")
g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
g.query("UNWIND range(0,49999) AS i CREATE (:Memory {id:i})")
g.query("UNWIND range(1,49999) AS i MATCH (a:Memory {id:i}),(b:Memory {id:i-1}) CREATE (a)-[:DERIVED_FROM]->(b)")
q = "MATCH (m:Memory {id:$i})-[:DERIVED_FROM*1..10]->(x) RETURN count(DISTINCT x)"
print("EXPLAIN:\n" + str(g.explain(q, {"i": 20000})))          # does not execute
print("PROFILE:\n" + str(g.profile(q, {"i": 20000})))          # executes; adds Records produced / Execution time per op
# raw commands (language-agnostic)
print("raw GRAPH.PROFILE:", db.connection.execute_command("GRAPH.PROFILE", "demo_explain", "RETURN 1")[:3])
# Per-query timeout (ms) -- applies to READ queries; raises ResponseError("Query timed out")
try:
    g.ro_query("MATCH (a:Memory),(b:Memory) RETURN count(*)", timeout=100)
except Exception as e: print("timeout ->", type(e).__name__, e)
# timeout on WRITE queries: server config TIMEOUT / TIMEOUT_MAX / TIMEOUT_DEFAULT (ms). Read the config:
print("GRAPH.CONFIG GET TIMEOUT*:", [db.connection.execute_command("GRAPH.CONFIG","GET",k) for k in ("TIMEOUT","TIMEOUT_DEFAULT","TIMEOUT_MAX")])
try:
    g.query("MATCH (a:Memory),(b:Memory) SET a.x=1", timeout=100)
except Exception as e: print("write timeout ->", type(e).__name__, e)
print("memory usage of graph (GRAPH.MEMORY USAGE):", db.connection.execute_command("GRAPH.MEMORY","USAGE","demo_explain")[:6])
print("slowlog:", g.slowlog()[:1])
