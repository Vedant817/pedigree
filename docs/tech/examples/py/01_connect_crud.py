"""Connect, CREATE/MERGE nodes+edges, parameterised Cypher, DELETE vs SET-invalidated, temporal props."""
from common import connect, fresh_graph
db = connect()
print("connected, graphs:", db.list_graphs())
g = fresh_graph(db, "demo_crud")

# Parameterised write. ALWAYS use params (also gives query-plan cache hits).
res = g.query(
    "CREATE (s:Source {id:$sid, kind:'web', trust:0.4, created_at: timestamp()}) "
    "CREATE (m:Memory {id:$mid, text:$text, status:'valid', taint:0.0, created_at: timestamp()}) "
    "CREATE (m)-[:DERIVED_FROM {at: timestamp(), weight:1.0}]->(s)",
    {"sid": "src1", "mid": "m1", "text": "Pricing page says plan costs $10"})
print("nodes_created", res.nodes_created, "rels_created", res.relationships_created,
      "props_set", res.properties_set, "run_time_ms", res.run_time_ms)

# Idempotent upsert (MERGE) with ON CREATE / ON MATCH
for i in range(2):
    r = g.query("MERGE (m:Memory {id:$id}) ON CREATE SET m.n=1 ON MATCH SET m.n = m.n + 1 RETURN m.n", {"id": "m2"})
    print("merge pass", i, "->", r.result_set[0][0])

# Batched upsert with UNWIND (the fast path; one round trip)
rows = [{"id": f"b{i}", "props": {"text": f"batch {i}", "status": "valid"}} for i in range(1000)]
r = g.query("UNWIND $rows AS row MERGE (m:Memory {id: row.id}) SET m += row.props", {"rows": rows})
print("batch nodes_created", r.nodes_created, "in", r.run_time_ms, "ms")

# MERGE on a relationship is idempotent
g.query("MATCH (a:Memory {id:'m2'}),(b:Memory {id:'m1'}) MERGE (a)-[:DERIVED_FROM]->(b)")
r = g.query("MATCH (a:Memory {id:'m2'}),(b:Memory {id:'m1'}) MERGE (a)-[:DERIVED_FROM]->(b)")
print("second MERGE rel created:", r.relationships_created)  # 0

# Soft invalidate (SET) -- keeps provenance, auditable
g.query("MATCH (m:Memory {id:'m1'}) SET m.status='invalidated', m.invalidated_at=timestamp(), m.invalid_reason=$why",
        {"why": "source retracted"})
print(g.query("MATCH (m:Memory {id:'m1'}) RETURN m.status, m.invalid_reason").result_set)

# Hard DELETE: deleting a node also deletes its incident edges (no DETACH needed; DETACH DELETE also accepted)
r = g.query("MATCH (m:Memory {id:'m1'}) DELETE m")
print("DELETE nodes_deleted", r.nodes_deleted, "rels_deleted", r.relationships_deleted)

# Temporal: no datetime(); use epoch-ms ints (timestamp()) or localdatetime()/date()/duration (stored as ints/ISO)
r = g.query("RETURN timestamp(), localdatetime('2026-10-15T10:00:00'), date('2026-10-15')")
print(r.result_set)
g.delete()
