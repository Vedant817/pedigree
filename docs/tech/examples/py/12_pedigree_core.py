"""Pedigree core prototype (VERIFIED against FalkorDB 4.22.1 and 4.18.3). Run: FALKOR_PORT=6390 python 12_pedigree_core.py
Model: every node has label :Node plus :Source/:Memory/:Action; edges child-[:DERIVED_FROM]->parent mirrored parent-[:FEEDS]->child;
(:Memory)-[:CORROBORATED_BY]->(:Source) = independent support. Status: ok|quarantined|tainted|preserved|revoked.
Revocation = barrier (atomic root revoke) -> discover+quarantine to fixpoint (BFS on FEEDS, chunked) -> compute final status in Python
(topological, support-preserving) -> chunked write -> verify loop."""
import time, collections
from common import connect, fresh_graph, wait_indexes

db = connect(); g = fresh_graph(db, "ped_proto")
g.query("CREATE INDEX FOR (n:Node) ON (n.id)"); wait_indexes(g)
db.connection.execute_command("GRAPH.CONSTRAINT", "CREATE", "ped_proto", "UNIQUE", "NODE", "Node", "PROPERTIES", "1", "id")
CHUNK = 2000

def add_node(label, id, **props):
    props.update(id=id, status=props.pop("status", "ok"), created_at=int(time.time()*1000))
    g.query(f"CREATE (n:Node:{label}) SET n = $p", {"p": props})   # label from a fixed allow-list in real code, never user input

def derive(child, parents, rel="derive", via="cite"):
    # atomic: edge + mirror + inherit flags (conf_eff union, low_integrity OR, status quarantined if any parent bad)
    r = g.query("""
      MATCH (c:Node {id:$c}) UNWIND $ps AS pid MATCH (p:Node {id:pid})
      MERGE (c)-[d:DERIVED_FROM]->(p) SET d.rel=$rel, d.via=$via
      MERGE (p)-[:FEEDS]->(c)
      WITH c, collect(p) AS parents
      SET c.low_integrity = coalesce(c.low_integrity,false) OR any(p IN parents WHERE p.low_integrity = true),
          c.status = CASE WHEN any(p IN parents WHERE p.status IN ['revoked','tainted','quarantined']) THEN 'quarantined' ELSE c.status END
      RETURN c.status""", {"c": child, "ps": parents, "rel": rel, "via": via})
    return r.result_set[0][0]

def corroborate(mem, src):
    g.query("MATCH (m:Memory {id:$m}), (s:Source {id:$s}) MERGE (m)-[:CORROBORATED_BY]->(s)", {"m": mem, "s": src})

def closure(root):  # read-only discovery; BFS over FEEDS excludes the root
    r = g.ro_query("MATCH (r:Node {id:$r}) CALL algo.BFS(r,-1,'FEEDS') YIELD nodes UNWIND nodes AS n RETURN n.id, n.status", {"r": root})
    return {row[0]: row[1] for row in r.result_set}

def chunks(xs, n=CHUNK):
    xs = list(xs)
    for i in range(0, len(xs), n): yield xs[i:i+n]

def compute_final(C, roots):
    """C: ids in closure. Returns {id: ('tainted'|'preserved'|'ok', taint_parent)} using parents+support read from the graph."""
    parents = collections.defaultdict(list); support = collections.defaultdict(list)
    for ch in chunks(C):
        for cid, pid in g.ro_query("UNWIND $ids AS i MATCH (c:Node {id:i})-[:DERIVED_FROM]->(p:Node) RETURN c.id, p.id", {"ids": ch}).result_set:
            parents[cid].append(pid)
        for mid, sid, st in g.ro_query("UNWIND $ids AS i MATCH (m:Memory {id:i})-[:CORROBORATED_BY]->(s:Source) RETURN m.id, s.id, s.status", {"ids": ch}).result_set:
            support[mid].append((sid, st))
    indeg = {c: sum(1 for p in parents[c] if p in C) for c in C}
    order, q = [], collections.deque([c for c in C if indeg[c] == 0]); kids = collections.defaultdict(list)
    for c in C:
        for p in parents[c]:
            if p in C: kids[p].append(c)
    while q:
        x = q.popleft(); order.append(x)
        for k in kids[x]:
            indeg[k] -= 1
            if indeg[k] == 0: q.append(k)
    assert len(order) == len(C), "cycle in derivation graph"
    final = {}
    for c in order:
        bad = [p for p in parents[c] if p in roots or final.get(p, ("ok",))[0] == "tainted"]
        if not bad: final[c] = ("ok", None); continue
        healthy = [s for s, st in support[c] if st == "ok"]
        final[c] = ("preserved", bad[0]) if healthy else ("tainted", bad[0])
    return final

def revoke(root, reason, hook=None):
    t0 = time.time()
    r = g.query("MATCH (r:Node {id:$r}) WHERE r.status <> 'revoked' SET r.status='revoked', r.revoked_at=timestamp(), r.reason=$why RETURN r.id", {"r": root, "why": reason})
    if not r.result_set: return {"idempotent": True}
    roots = {x[0] for x in g.ro_query("MATCH (r:Node {status:'revoked'}) RETURN r.id").result_set}
    for it in range(10):                     # barrier fixpoint: quarantine everything reachable
        C = {}
        for rt in roots: C.update(closure(rt))
        todo = [i for i, st in C.items() if st in ("ok", "preserved")]
        if hook and it == 0: hook()          # test hook: concurrent ingest between discovery and quarantine
        if not todo: break
        for ch in chunks(todo): g.query("UNWIND $ids AS i MATCH (n:Node {id:i}) SET n.status='quarantined'", {"ids": ch})
    else: raise RuntimeError("barrier did not converge")
    for _ in range(5):                       # compute + write final; re-verify no new quarantined nodes appeared
        C = set(); [C.update(closure(rt)) for rt in roots]
        final = compute_final(C, roots)
        for ch in chunks(final.items()):
            g.query("UNWIND $b AS b MATCH (n:Node {id:b[0]}) SET n.status=b[1][0], n.taint_parent=b[1][1]", {"b": [[k, [v[0], v[1]]] for k, v in ch]})
        left = [i for i, st in {k: v for rt in roots for k, v in closure(rt).items()}.items() if st == "quarantined"]
        if not left: break
    counts = collections.Counter(v[0] for v in final.values())
    acts = g.ro_query("UNWIND $ids AS i MATCH (a:Action {id:i}) WHERE a.status='tainted' RETURN a.id, a.effect", {"ids": list(final)}).result_set
    return {"counts": dict(counts), "actions": acts, "ms": round((time.time()-t0)*1000, 1)}

# ---- scenario: web page s_web (untrusted) poisons m1; m2 corroborated by independent source; m3 derives from m1+m2; action commits
add_node("Source", "s_web", kind="web", low_integrity=True, conf=[])
add_node("Source", "s_doc", kind="file", low_integrity=False, conf=[])
add_node("Source", "s_hr",  kind="file", low_integrity=False, conf=["hr"])
for m in ["m1", "m2", "m3", "m4", "m5", "m6"]: add_node("Memory", m, conf=[])
add_node("Action", "a_commit", tool="git commit", effect="reversible"); add_node("Action", "a_push", tool="git push", effect="irreversible")
derive("m1", ["s_web"]); derive("m2", ["s_web"]); corroborate("m2", "s_doc")      # m2: tainted path but independent support
derive("m3", ["m1", "m2"]); derive("m4", ["m2"])                                    # m4 only depends on preserved m2 -> should be ok
derive("m5", ["s_doc"]);   derive("m6", ["m3"])
derive("a_commit", ["m3"], rel="rely"); derive("a_push", ["m6", "m5"], rel="rely", via="session_read")
res = revoke("s_web", "malicious page")
print("revoke:", res)
st = dict(g.ro_query("MATCH (n:Node) RETURN n.id, n.status").result_set)
print(st)
assert st["s_web"] == "revoked" and st["m1"] == "tainted" and st["m2"] == "preserved" and st["m3"] == "tainted" and st["m4"] == "ok" \
   and st["m5"] == "ok" and st["m6"] == "tainted" and st["a_commit"] == "tainted" and st["a_push"] == "tainted"
assert sorted(x[0] for x in res["actions"]) == ["a_commit", "a_push"]
assert revoke("s_web", "again") == {"idempotent": True}

# blame via taint_parent chain (no shortestPath needed)
chain, cur = [], "a_push"
while cur:
    chain.append(cur); cur = g.ro_query("MATCH (n:Node {id:$i}) RETURN n.taint_parent", {"i": cur}).result_set[0][0]
print("blame chain a_push:", chain); assert chain == ["a_push", "m6", "m3", "m1", "s_web"]

# confidentiality: conf_eff flows at write time; gate rule: any tag not in audience => block
g.query("MATCH (s:Source {id:'s_hr'}) SET s.conf_eff=['hr']"); g.query("MATCH (n:Node) WHERE n.conf_eff IS NULL SET n.conf_eff = coalesce(n.conf, [])")
add_node("Memory", "m_sum", conf=[]); 
g.query("""MATCH (c:Memory {id:'m_sum'}), (p:Node {id:'s_hr'}) MERGE (c)-[:DERIVED_FROM]->(p) MERGE (p)-[:FEEDS]->(c)
           SET c.conf_eff = p.conf_eff""")
r = g.ro_query("MATCH (m:Node) WHERE m.id IN $ids WITH m WHERE any(t IN m.conf_eff WHERE NOT t IN $aud) RETURN m.id", {"ids": ["m_sum", "m5"], "aud": ["public"]})
print("conf leak check ->", r.result_set); assert r.result_set == [["m_sum"]]

# PageRank over DERIVED_FROM: parents accumulate rank -> load-bearing sources
r = g.ro_query("CALL algo.pageRank('Node','DERIVED_FROM') YIELD node, score WHERE 'Source' IN labels(node) RETURN node.id, score ORDER BY score DESC LIMIT 3").result_set
print("load-bearing sources:", r)

# GRAPH.COPY what-if
t = time.time(); g.copy("ped_proto__wi_test"); w = db.select_graph("ped_proto__wi_test")
print("copy ms:", round((time.time()-t)*1000, 1), "| indexes kept:", len(w.ro_query("CALL db.indexes()").result_set))
w.query("MATCH (n:Node {id:'s_doc'}) SET n.status='revoked'"); w.delete()

# ---- race: a concurrent ingest between discovery and quarantine must still end up tainted (barrier fixpoint)
add_node("Source", "s_bad", kind="web", low_integrity=True, conf=[]); add_node("Memory", "r1", conf=[]); derive("r1", ["s_bad"])
def concurrent_ingest():
    add_node("Memory", "r_late", conf=[]); derive("r_late", ["r1"])        # parent r1 still 'ok' at this instant
res = revoke("s_bad", "race test", hook=concurrent_ingest)
st = dict(g.ro_query("MATCH (n:Node) WHERE n.id IN ['r1','r_late'] RETURN n.id, n.status").result_set)
print("race:", st); assert st == {"r1": "tainted", "r_late": "tainted"}
# ingest AFTER revocation inherits quarantine atomically, never 'ok'
add_node("Memory", "r_after", conf=[]); stt = derive("r_after", ["r1"]); print("late child status at creation:", stt); assert stt == "quarantined"
print("OK")
