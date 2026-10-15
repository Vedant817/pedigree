"""Vector index (HNSW) + fulltext index + hybrid (vector seed -> graph expand). Latency at 20k x 384-d."""
import random, time, math
from common import connect, fresh_graph, summarize, wait_indexes
db = connect(); g = fresh_graph(db, "demo_vec")
DIM, N = 384, 20000
random.seed(1)
def rv(): 
    v = [random.gauss(0, 1) for _ in range(DIM)]; n = math.sqrt(sum(x*x for x in v)); return [x/n for x in v]
vecs = [rv() for _ in range(N)]
words = ["pricing","refund","invoice","vendor","contract","launch","bug","outage","customer","policy","retracted","source"]
rows = [{"id": i, "text": " ".join(random.sample(words, 4)) + f" memory{i}", "emb": vecs[i]} for i in range(N)]
t = time.time()
for k in range(0, N, 2000):   # NOTE: vecf32() must be applied inside Cypher; plain python lists are stored as ARRAYS otherwise
    g.query("UNWIND $rows AS r CREATE (:Memory {id:r.id, text:r.text, emb: vecf32(r.emb)})", {"rows": rows[k:k+2000]})
print(f"inserted {N}x{DIM}d in {time.time()-t:.2f}s")
t = time.time()
g.query(f"CREATE VECTOR INDEX FOR (m:Memory) ON (m.emb) OPTIONS {{dimension:{DIM}, similarityFunction:'cosine', M:16, efConstruction:200, efRuntime:50}}")
print(f"vector index CREATE returned in {time.time()-t:.2f}s (build continues async)")
t = time.time(); g.query("CREATE FULLTEXT INDEX FOR (m:Memory) ON (m.text)"); print(f"fulltext index build: {time.time()-t:.2f}s")
g.query("CREATE INDEX FOR (m:Memory) ON (m.id)")
print(f"waited {wait_indexes(g):.2f}s more for async index build to become OPERATIONAL")
lat = []; hits = 0
for i in range(200):
    q = vecs[i]
    t = time.perf_counter()
    r = g.ro_query("CALL db.idx.vector.queryNodes('Memory','emb',5,vecf32($v)) YIELD node,score RETURN node.id,score", {"v": q})
    lat.append((time.perf_counter()-t)*1000); hits += (r.result_set[0][0] == i)
print(summarize("vector top5 (20k x 384d)", lat), f"self-recall@1={hits}/200")
print("score semantics: cosine DISTANCE (0 = identical, lower is better):", r.result_set[:2])
# hybrid: vector search seeds, then graph expansion in the same query
g.query("UNWIND range(1,1999) AS i MATCH (a:Memory {id:i}),(b:Memory {id:i-1}) CREATE (a)-[:DERIVED_FROM]->(b)")
r = g.ro_query("""
CALL db.idx.vector.queryNodes('Memory','emb',3,vecf32($v)) YIELD node, score
MATCH (node)-[:DERIVED_FROM*1..3]->(anc:Memory)
RETURN node.id, score, collect(DISTINCT anc.id) AS ancestors ORDER BY score""", {"v": vecs[1500]})
print("hybrid vector->graph:", r.result_set)
lat = []
for w in ["pricing", "refund invoice", "outage*", "memory123"]:
    t = time.perf_counter()
    r = g.ro_query("CALL db.idx.fulltext.queryNodes('Memory',$q) YIELD node,score RETURN count(*)", {"q": w})
    lat.append((time.perf_counter()-t)*1000); print(f"fulltext {w!r:20} -> {r.result_set[0][0]} hits {lat[-1]:.1f}ms")
# Filtered vector search: the filter is applied AFTER the ANN top-k (post-filter) -> you can get < k results
r = g.ro_query("CALL db.idx.vector.queryNodes('Memory','emb',10,vecf32($v)) YIELD node,score WHERE node.id % 2 = 0 RETURN count(*)", {"v": vecs[7]})
print("post-filtered top10 (only even ids) returns", r.result_set[0][0], "rows (<10 expected)")
