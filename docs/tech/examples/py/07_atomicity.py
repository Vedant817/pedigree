"""What is / is not atomic. Verified against 4.18.3."""
from common import connect, fresh_graph
db = connect(); g = fresh_graph(db, "demo_atomic")
g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
g.query("CREATE (:Memory {id:'m1', status:'valid'})")
db.connection.execute_command("GRAPH.CONSTRAINT","CREATE","demo_atomic","UNIQUE","NODE","Memory","PROPERTIES","1","id")
import time; time.sleep(0.5)
count = lambda: g.ro_query("MATCH (m:Memory) RETURN count(m)").result_set[0][0]

# 1. Single query = atomic: the 2nd CREATE violates the unique constraint -> whole query (incl. first CREATE and the SET) rolls back
try:
    g.query("CREATE (:Memory {id:'new1'}) WITH 1 AS x MATCH (m:Memory {id:'m1'}) SET m.status='X' CREATE (:Memory {id:'m1'})")
except Exception as e: print("expected failure:", e)
print("after failed multi-clause write: count =", count(), "(expect 1);",
      "status =", g.ro_query("MATCH (m:Memory {id:'m1'}) RETURN m.status").result_set[0][0], "(expect valid)")
assert count() == 1

# 2. UNWIND batch is atomic too: one bad row => nothing written
try:
    g.query("UNWIND $rows AS r CREATE (:Memory {id:r})", {"rows": ["ok1", "ok2", "m1"]})
except Exception as e: print("expected failure:", e)
assert count() == 1; print("batch rolled back as a whole: count =", count())

# 3. TWO separate queries are NOT atomic together. Use MULTI/EXEC (pipeline(transaction=True)) -- but errors inside EXEC do NOT roll back
#    earlier commands (Redis semantics): each GRAPH.QUERY is atomic individually; the EXEC block is only isolated, not all-or-nothing.
pipe = db.connection.pipeline(transaction=True)
pipe.execute_command("GRAPH.QUERY", "demo_atomic", "CREATE (:Memory {id:'tx1'})")
pipe.execute_command("GRAPH.QUERY", "demo_atomic", "CREATE (:Memory {id:'m1'})")      # violates constraint
pipe.execute_command("GRAPH.QUERY", "demo_atomic", "CREATE (:Memory {id:'tx2'})")
res = pipe.execute(raise_on_error=False)
print("MULTI/EXEC results types:", [type(r).__name__ for r in res])
print("after MULTI/EXEC with one failing command: count =", count(), "(tx1 and tx2 persisted => NOT all-or-nothing)")
assert count() == 3

# 4. Read-your-writes inside a query, and DELETE then re-create in one query
r = g.query("MATCH (m:Memory {id:'tx1'}) DELETE m WITH 1 AS x CREATE (:Memory {id:'tx1'}) RETURN 1")
print("delete+recreate same unique key in one query ->", r.result_set, "(works: delete is applied before the create)")

# 5. Cross-graph writes are never atomic (different keys). MULTI/EXEC blocks other clients but cannot rollback.
# 6. Optimistic concurrency / compare-and-set pattern for single rows: one query, check in WHERE
r = g.query("MATCH (m:Memory {id:'m1', status:'valid'}) SET m.status='locked', m.owner=$o RETURN count(m)", {"o": "agentA"})
print("CAS #1 won:", r.result_set[0][0])
r = g.query("MATCH (m:Memory {id:'m1', status:'valid'}) SET m.status='locked', m.owner=$o RETURN count(m)", {"o": "agentB"})
print("CAS #2 won:", r.result_set[0][0], "(0 = lost)")
