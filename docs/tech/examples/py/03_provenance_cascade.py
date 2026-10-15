"""Core model for the provenance/taint/revocation layer. Runs on a tiny diamond DAG and asserts results.

 (:Source {id,kind,trust,status})   <-[:DERIVED_FROM]-  (:Memory {id,status,trust_eff,...})
 (:Memory)  <-[:DEPENDS_ON]-  (:Decision {id,...})
 (:Agent)-[:WROTE]->(:Memory)
Edges point from the derived thing TO its origin: (child)-[:DERIVED_FROM]->(parent).
"""
from common import connect, fresh_graph
db = connect(); g = fresh_graph(db, "demo_prov")
g.query("CREATE INDEX FOR (n:Memory) ON (n.id)"); g.query("CREATE INDEX FOR (n:Source) ON (n.id)"); g.query("CREATE INDEX FOR (n:Decision) ON (n.id)")
g.query("""
CREATE (s1:Source {id:'s1', kind:'web',   trust:0.3, status:'active'}),
       (s2:Source {id:'s2', kind:'doc',    trust:0.9, status:'active'}),
       (a:Memory {id:'a', status:'valid'}), (b:Memory {id:'b', status:'valid'}),
       (c:Memory {id:'c', status:'valid'}), (d:Memory {id:'d', status:'valid'}), (z:Memory {id:'z', status:'valid'}),
       (a)-[:DERIVED_FROM]->(s1), (b)-[:DERIVED_FROM]->(s2),
       (c)-[:DERIVED_FROM]->(a), (c)-[:DERIVED_FROM]->(b),          // diamond: c has two parents (one tainted path)
       (d)-[:DERIVED_FROM]->(c), (z)-[:DERIVED_FROM]->(s2),
       (:Decision {id:'dec1', title:'Ship pricing change'})-[:DEPENDS_ON]->(d),
       (:Decision {id:'dec2', title:'Email vendor'})-[:DEPENDS_ON]->(z)
""")

# 1. TAINT / TRUST PROPAGATION by traversal: effective trust = min trust over every reachable Source.
r = g.query("""
MATCH (m:Memory)-[:DERIVED_FROM*1..10]->(s:Source)
WITH m, min(s.trust) AS t, count(DISTINCT s) AS n_src
SET m.trust_eff = t
RETURN m.id, t, n_src ORDER BY m.id""")
print("trust_eff:", r.result_set)
assert dict((x[0], x[1]) for x in r.result_set) == {'a': 0.3, 'b': 0.9, 'c': 0.3, 'd': 0.3, 'z': 0.9}

# 2. EXPLAIN WHY: all provenance paths from d back to sources (audit trail)
r = g.query("""
MATCH p=(d:Memory {id:$id})-[:DERIVED_FROM*1..10]->(s:Source)
RETURN s.id, length(p) AS hops, [n IN nodes(p) | n.id] AS chain ORDER BY hops, s.id""", {"id": "d"})
print("provenance paths of d:"); [print("  ", x) for x in r.result_set]

# 3. IMPACT PREVIEW (read-only): what would retracting s1 invalidate? DISTINCT is required (diamonds => duplicate rows)
q_preview = """
MATCH (s:Source {id:$sid})<-[:DERIVED_FROM*1..10]-(m:Memory)
RETURN DISTINCT m.id ORDER BY m.id"""
print("preview s1:", g.ro_query(q_preview, {"sid": "s1"}).result_set)

# 4. CASCADE RETRACT, atomic in ONE query (single writer; no other query interleaves): mark source, mark every descendant,
#    return the decisions that depend on any invalidated memory.
q_retract = """
MATCH (s:Source {id:$sid})
SET s.status='retracted', s.retracted_at=timestamp(), s.retract_reason=$why
WITH s
MATCH (s)<-[:DERIVED_FROM*1..10]-(m:Memory)
WITH DISTINCT s, m
SET m.status='invalidated', m.invalidated_at=timestamp(), m.invalidated_by=s.id
RETURN count(m) AS n"""
r = g.query(q_retract, {"sid": "s1", "why": "found to be wrong"})
print("invalidated count:", r.result_set, "props_set:", r.properties_set)
assert r.result_set[0][0] == 3  # a, c, d
dec = g.ro_query("""
MATCH (d:Decision)-[:DEPENDS_ON]->(m:Memory {status:'invalidated'})
RETURN d.id, d.title, collect(DISTINCT m.id) AS because ORDER BY d.id""").result_set
print("decisions to revisit:", dec)
assert [x[0] for x in dec] == ['dec1']
# Memory b is untouched (other source), z unaffected
print("still valid:", g.ro_query("MATCH (m:Memory {status:'valid'}) RETURN m.id ORDER BY m.id").result_set)

# 5. Dependent decisions can ALSO be reached transitively in one hop-pattern (Decision -> Memory -> ... -> Source):
print("decisions affected by s1 (transitive, read-only):", g.ro_query("""
MATCH (s:Source {id:'s1'})<-[:DERIVED_FROM*1..10]-(m:Memory)<-[:DEPENDS_ON]-(d:Decision)
RETURN DISTINCT d.id""").result_set)

# 6. Reinstate: only memories whose *all* paths are clean may be revalidated. Pattern: reset all descendants, then re-run
#    the cascade for every source that is still retracted (idempotent, order-independent).
g.query("MATCH (s:Source {id:'s1'}) SET s.status='active' REMOVE s.retract_reason WITH s "
        "MATCH (s)<-[:DERIVED_FROM*1..10]-(m:Memory) SET m.status='valid' REMOVE m.invalidated_by")
g.query("MATCH (s:Source {status:'retracted'})<-[:DERIVED_FROM*1..10]-(m:Memory) SET m.status='invalidated'")
print("after reinstate:", g.ro_query("MATCH (m:Memory) RETURN m.status, count(*) ORDER BY m.status").result_set)
print("OK")
