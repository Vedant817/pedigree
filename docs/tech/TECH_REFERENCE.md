# FalkorDB technical reference — provenance / taint / revocation layer for agent memory
Box: Linux x64, Python 3.13, Node 20.19, glibc ≥2.39, **no Docker**. Date of research: 2026-10-15 (IST).
Tags: **[V]** = verified by running it here; **[D]** = from docs/GitHub/PyPI only (not run); **[J]** = my judgement.
Event: Oct 15–18 2026, deadline Oct 18 11:59 PM IST. Submission needs public repo, README (setup + graph data model + the Cypher it depends on), demo video, live deploy OR full local setup. See GOTCHAS.md for traps.

## 1. Running FalkorDB with no Docker  [V]
```bash
cd /workspace/falkordb-hack/tech
python3 -m venv .venv && . .venv/bin/activate
pip install falkordblite==0.10.0 falkordb==1.8.0 "mcp>=2,<3"       # wheel 34-36 MB; venv ~159 MB
./start-falkordb.sh            # real server on :6379 (PORT=... to change), RDB+AOF in ./data
```
- The `falkordblite` wheel ships `redislite/bin/redis-server` (Redis 8.6.2), `redis-cli` and `falkordb.so` (FalkorDB **4.18.3**). `start-falkordb.sh` loads it with `--loadmodule` — it is a normal network server, any client works. Needs glibc ≥ 2.39 (manylinux_2_39; cp312/313/314).
- **Newer engine, still no Docker [V]:** download the official release asset and load it into the same redis-server:
  `curl -L -o bin/falkordb-4.22.1-x64.so https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.1/falkordb-x64.so && chmod +x bin/*.so && FALKOR_SO=$PWD/bin/falkordb-4.22.1-x64.so ./start-falkordb.sh`
  (51 MB; **forgot chmod → "does not have execute permissions", server aborts**). On 4.22.1 I re-ran examples 03 and 04 (pass), `DUMP/RESTORE` of a 20k-node graph (works now; crashed on 4.18.3), and scale bench (numbers ≈ same, bench/scale_dense_v4221.txt). New procedures there: `algo.AStar, algo.HarmonicCentrality, algo.maxFlow, db.idx.cch.query`.
- **Version landscape [D]:** Docker `falkordb/falkordb:latest` now = Rust-engine **6.0.x** (6.0.2, 2026-10-08; same GRAPH.* + Cypher; A*/CCH not ported yet; FT/vector run on RediSearch 8.6.1). Latest C engine = **v4.22.1** (2026-10-15). `latest-alpine` = 4.20.7. 6.0.x has no `.so` release asset (asset list empty) so I could NOT run it. **[J] Pin `falkordb/falkordb:v4.22.1` (or the 4.18.3 wheel) and test; don't rely on `latest`.** License: SSPLv1.
- Docker, if Vedant has it: `docker run -p 6379:6379 -p 3000:3000 -v falkor:/var/lib/falkordb/data falkordb/falkordb:v4.22.1` (image ~185 MB compressed; bundles Browser on :3000) **[D]**. Config via `-e FALKORDB_ARGS="TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824"` **[D]**.
- **Mandatory config [V]:** `TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`. Defaults are all 0 (unlimited) and a runaway write then ignores per-query TIMEOUT and OOM-killed the whole server (6.3 GB RSS). Set at load time or `GRAPH.CONFIG SET`.
- FalkorDB Browser (UI): `git clone https://github.com/FalkorDB/falkordb-browser; npm ci; NEXTAUTH_URL=http://localhost:3000 AUTH_SECRET=x npx next dev -p 3000` returned HTTP 200 on Node 20 (package.json says node ≥24); login UI not exercised **[partly V]**.

## 2. Clients
**Python `falkordb` 1.8.0 [V]**
```python
from falkordb import FalkorDB
db = FalkorDB(host="localhost", port=6379)          # also password=, ssl=True for Cloud paid tiers
g = db.select_graph("tenant_acme")                  # graph is created lazily on first write
r = g.query("MERGE (m:Memory {id:$id}) SET m.status='valid' RETURN m", {"id":"m1"}, timeout=5000)
r.result_set; r.run_time_ms; r.nodes_created; r.properties_set
g.ro_query(...)            # read-only, replica-safe
g.copy("tenant_acme_backup"); g.delete(); db.list_graphs()
g.explain("MATCH ..."); db.connection.execute_command("GRAPH.PROFILE", "g", "MATCH ...")   # g.profile() str output omits stats
```
**Node `falkordb` 6.8.0 [V]** `const db = await FalkorDB.connect({socket:{host,port}}); const g = db.selectGraph("t"); const r = await g.query(q,{params,TIMEOUT:5000}); r.data; r.metadata; g.roQuery(...)`. See `examples/node/01_basic.mjs`.

## 3. Data model used by the examples [V] (examples/py/03_provenance_cascade.py)
```
(:Source {id,kind,trust,status})  <-[:DERIVED_FROM]-  (:Memory {id,status,trust_eff,...})  <-[:DEPENDS_ON]-  (:Decision {id,title})
(:Agent)-[:WROTE]->(:Memory)          one graph per tenant (graph name = tenant id)
```
For scale write BOTH `(child)-[:DERIVED_FROM]->(parent)` (why) and `(parent)-[:FEEDS]->(child)` (impact), because `algo.BFS` follows only outgoing edges of one type.
Key Cypher (all [V]):
```cypher
CREATE INDEX FOR (n:Memory) ON (n.id)                       -- async! see §4
-- trust propagation (min over reachable sources)
MATCH (m:Memory)-[:DERIVED_FROM*1..10]->(s:Source) WITH m, min(s.trust) AS t SET m.trust_eff=t
-- explain why
MATCH p=(d:Memory {id:$id})-[:DERIVED_FROM*1..10]->(s:Source) RETURN s.id, length(p), [n IN nodes(p)|n.id]
-- cascade retract, ONE atomic query, linear time (BFS excludes the start node; returns nodes in undefined order)
MATCH (s:Source {id:$sid}) SET s.status='retracted', s.retracted_at=timestamp()
WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m
SET m.status='invalidated', m.invalidated_by=s.id RETURN count(m)
-- dependent decisions
MATCH (s:Source {id:$sid}) CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m
MATCH (m)<-[:DEPENDS_ON]-(d:Decision) RETURN DISTINCT d.id, d.title
-- ancestors (audit): MATCH (m:Memory {id:$m}) CALL algo.BFS(m,10,'DERIVED_FROM') YIELD nodes RETURN nodes
```
Small graphs: `[:DERIVED_FROM*1..10]` + `RETURN DISTINCT` is fine and simpler. Dense DAGs: use BFS (§5). Reinstate pattern (reset descendants, re-run cascade for still-retracted sources) is in the example. Generalises to a decision-tracking company brain: `Decision`, `Fact`, `Document`, `Person` nodes with the same DERIVED_FROM/DEPENDS_ON edges, `SUPERSEDES` for versioning.

## 4. Feature verification table (4.18.3 unless noted)
| Feature | Result |
|---|---|
| Multi-graph / tenants | [V] 200 graphs: create+index+node p50 0.94 ms / p95 1.43 ms; cross-tenant point read p50 0.45 ms; delete 0.22 ms; isolation asserted. 1000 graphs ≈ 0.41 GiB (≈422 KiB/graph, ≈570 KiB with one index). 1000 reads over 1000 tenants 0.66 s. |
| MERGE / UNWIND batch / params | [V] idempotent, ON CREATE/ON MATCH ok |
| Algorithms | [V] `algo.BFS, MSF, SPpaths, SSpaths, WCC, betweenness, labelPropagation, pageRank` (+AStar, HarmonicCentrality, maxFlow, CCH on 4.22.1). **No** louvain/leiden/CDLP/triangleCount, no APOC, no regex op, no UDF, no `datetime()` (use `timestamp()`, `localdatetime()`, `date()`). Full list: bench/procedures.txt |
| Vector | [V] `CREATE VECTOR INDEX FOR (n:Memory) ON (n.emb) OPTIONS {dimension:384, similarityFunction:'cosine'}` ; store `vecf32([...])`; `CALL db.idx.vector.queryNodes('Memory','emb',5,vecf32($q)) YIELD node, score`. Score = **distance** (lower better). 20k×384: insert 7.5 s, index build ≈10.6 s (async), top-5 p50 0.88 ms / p95 1.29 ms, self-recall@1 200/200. Filtering is post-ANN (asked 10, got 4). Dim 1–4096. |
| Full-text | [V] `CALL db.idx.fulltext.createNodeIndex('Memory','text')` then `db.idx.fulltext.queryNodes('Memory','term') YIELD node,score`; 20k docs build ≈4.5 s; query 0.5–5 ms. Hybrid vector→graph expansion works. |
| Constraints | [V] needs exact-match index first, then `GRAPH.CONSTRAINT CREATE g UNIQUE NODE Memory PROPERTIES 1 id` (starts PENDING). Violation rolls back whole query. |
| EXPLAIN / PROFILE / timeouts | [V] see bench/explain_profile_timeout.txt; with TIMEOUT_MAX set, write timeouts roll back ("Query timed out"); timeout > TIMEOUT_MAX errors; mem cap error "Query's mem consumption exceeded capacity". |
| Atomicity | [V] one query (incl. UNWIND batches, multi-clause writes) is all-or-nothing. **MULTI/EXEC is NOT**: earlier commands persisted when a later one failed. CAS in one query works (`MATCH (m {id:$i, v:$old}) SET m.v=$new RETURN count(m)`). |
| Concurrency | [V] reads scale: 1/2/4/8/16 readers = 279/559/1225/1643/1562 q/s. Writes serialised per graph ≈5.3k/s (1 or 4 writers); ≈9–10k/s over several graphs. A 0.5–0.7 s cascade write stalled readers: same-graph reader p95 452 ms (5 ms idle); a reader on a *different* graph also stalled (≈14 reads vs ≈200 expected) — mechanism not verified. |
| Persistence | [V] AOF everysec + RDB: `kill -9` + restart kept 5000 nodes + index. `SAVE` ok. `GRAPH.COPY src dst`: 20k nodes+20k edges ≈165 ms, keeps indexes → demo reset = delete+copy ≈170–190 ms. `DUMP/RESTORE` of a graph key crashes 4.18.3 (fixed in 4.22.1 [V]). |
| Memory | [V] 100k nodes+500k edges: RSS 363 MiB (empty server 45), `GRAPH.MEMORY USAGE` 42 MB, used_memory 68 MiB. RSS does not shrink after deletes. |

## 5. Scale benchmark — 105k nodes (1k Source, 99k Memory in 10 levels, 5k Decision), 495k DERIVED_FROM + 495k FEEDS + 15k DEPENDS_ON; ingest ≈26 s [V]
| Op (4.18.3; 4.22.1 in brackets) | dense (5 random parents/level) | local (clustered) |
|---|---|---|
| Impact preview, BFS depth 10 | p50 12.7 ms / p95 17.6 (12.4/14.1); ~65k affected | p50 5.5 / p95 7.1; ~12k affected |
| **Atomic cascade write, 1 query** | **p50 546 ms / p95 714** (502/559) ≈8 µs/node | p50 104 / p95 133 |
| Dependent decisions (5000 decisions) | p50 84 / p95 106 (78/100) | p50 20.6 / p95 30.2 |
| Ancestors via BFS (~41k) | p50 25.8 / p95 34.6 (18.7/37.1) | p50 5.1 / p95 13.3 |
| Var-length `FEEDS*1..k` (path enumeration) | 4.9 ms k=2; 118 ms k=6; 2.1 s k=8; **timeout 10 s k=10** | 3 s k=8; timeout k=10 |
| Wave cascade (≤10 queries, not atomic overall) | ≈1.2 s | p50 449 ms |
Layered-DAG toy test: var-length k=5 46 ms, k=6 340 ms, k=7 2.75 s, beyond = timeout, while `algo.BFS` was 0.6 ms. **Rule: BFS for reach/cascade on anything dense; var-length only with small depth + DISTINCT.** Bound or chunk cascades >50k nodes (they block other queries). Raw: bench/scale_*.txt/json, bench/scale_dense_v4221.txt.

## 6. Integration surface (none of these were run end-to-end; no LLM key on box)
| Project | Facts | Fit |
|---|---|---|
| **FalkorDB MCP** `@falkordb/mcpserver` 1.3.0 (MIT, TS) | [V over stdio] generic Cypher passthrough: query_graph, query_graph_readonly, list_graphs, delete_graph, get_graph_schema, get_node_schema, get_relationship_schema. Env FALKORDB_HOST/PORT/USERNAME/PASSWORD/TLS; HTTP via `MCP_TRANSPORT=http MCP_PORT=..`. `npx -y @falkordb/mcpserver`. **No tenant isolation** (any graphName). | Good for a "raw access" baseline; build a custom server for provenance tools. |
| GraphRAG-SDK `graphrag-sdk` 1.4.0 (Apache-2.0, ~1k★) | [V] `pip install` **fails here**: dep `hnswlib` is sdist-only and needs g++ (absent); dep `gliner` pulls **torch** (GBs). LLM via LiteLLM/OpenAI/Anthropic/OpenRouter; requires LLM key. | Too heavy for the disk budget; skip. |
| Graphiti `graphiti-core[falkordb]` 0.30.2 (Apache-2.0, ~32k★) | [V] install = 156 MB venv, but `import graphiti_core` failed `ModuleNotFoundError: httpx` until `pip install httpx`. `FalkorDriver(host, port, username, password, falkor_db=None, database='default_db')` — `database` = graph name (tenant). Needs LLM+embedder to ingest [D]. Temporal-edge knowledge graph; closest prior art for "memory". | Optional inspiration/baseline. |
| Cognee `cognee` 1.6.4 | [V] default install = **1.5 GB** venv. Deleted. | Avoid. |
| QueryWeaver `queryweaver` 0.3.2 | [D] AGPL-3.0, text-to-SQL | Not relevant. |
| LangChain `langchain-falkordb` 0.2.0, LlamaIndex `llama-index-graph-stores-falkordb` 0.7.0, `falkordb-bulk-loader` 1.2.0 | [D] only versions confirmed | Not needed; native client is enough. |

## 7. MCP server (Python + TypeScript) [V]  — examples/mcp/
- Tools: `add_memory, retract_source, explain_memory` (tenant passed as a parameter → graph name; **[J]** validate/allow-list tenant ids and derive from auth, never trust the agent).
- Python: `pip install "mcp>=2,<3" falkordb`; `from mcp.server.mcpserver import MCPServer` (v2 renamed FastMCP; `mcp.server.fastmcp` → ModuleNotFoundError; pin `mcp<2` for FastMCP code; server_py.py falls back to FastMCP). Transport args move to `run()`: `mcp.run("streamable-http", host, port)`. Client: `from mcp import Client, StdioServerParameters`.
  `python examples/mcp/server_py.py` (stdio) | `... http 8765` (→ `http://127.0.0.1:8765/mcp`); smoke: `python examples/mcp/client_smoke.py` — stdio **and** HTTP passed.
- TypeScript: `cd examples/mcp/ts && npm i` (`@modelcontextprotocol/sdk` 1.32.1 v1 API `McpServer.registerTool`, express 5, zod 4, falkordb 6.8). `node server_ts.mjs` (stdio) / `node server_ts.mjs http`; `node client_smoke.mjs` — stdio + stateless streamable HTTP passed. npm also has v2 split packages (`@modelcontextprotocol/server` 2.3.1) — untested.
- **OpenCode config** (docs opencode.ai/docs/mcp-servers; I did not run OpenCode itself) [D]: `opencode.json` at repo root; see examples/mcp/opencode.json:
```json
{ "$schema":"https://opencode.ai/config.json",
  "mcp": {
    "provenance": {"type":"local","command":["python","examples/mcp/server_py.py"],
                   "environment":{"FALKOR_HOST":"localhost","FALKOR_PORT":"6379"},"enabled":true,"timeout":10000},
    "provenance_remote": {"type":"remote","url":"http://127.0.0.1:8765/mcp","oauth":false,
                   "headers":{"Authorization":"Bearer {env:MCP_TOKEN}"},"enabled":false} } }
```
`command` is an array; `timeout` default 5000 ms (raise it); tools appear prefixed by server name (`provenance_add_memory`); disable via `"tools":{"provenance_*":false}`.

## 8. Free, no-card LLM / embeddings  (docs/search only unless marked; limits change — check console)
| Option | Notes |
|---|---|
| **Gemini API (Google AI Studio)** | Free tier, no card: gemini-3.8-flash, 3.6-flash, 3.5-flash-lite, 3.1-flash-lite, 2.5-pro/flash/flash-lite, `gemini-embedding-2` (free). Exact RPM/RPD only visible in AI Studio; per-project; daily reset midnight Pacific; **free-tier data is used to improve Google products**. 3.1-pro-preview & gemini-4-argon NOT free. |
| **Groq** | Free, no card. gpt-oss-120b / gpt-oss-20b / qwen3.8-27b: 30 RPM, 1K RPD, 8K TPM, 200K TPD; compound 30 RPM/250 RPD. |
| OpenRouter `:free` models | No card; 20 RPM, 50 RPD (1000 RPD after $10 purchase); failed calls count. |
| Mistral free mode | no card; limits only in console; third-party claims ~1 RPS, phone verify, data trained on [unverified]. |
| Cloudflare Workers AI | 10,000 Neurons/day, no card; JSON-schema mode + function calling on selected models. |
| ✗ Cerebras (needs verified payment method), ✗ GitHub Models (retired 2026-07-30) | |
| **Local embeddings [V]** | `pip install fastembed==0.9.0`; `TextEmbedding("BAAI/bge-small-en-v1.5")` → 384-d, ≈1.1 ms/doc CPU, 65 MB model cache, venv ≈221 MB incl. onnxruntime. Pair with the vector index dim 384. |
**[J]** Demo should not *require* an LLM: provenance/taint/cascade are pure graph ops. Use LLM only for optional fact extraction; Gemini free or Groq; embeddings via fastembed (no quota).

## 9. Free, no-card deployment
| Option | Facts [D] |
|---|---|
| **FalkorDB Cloud Free** | $0, no card; 100 MB RAM/dataset; AWS or GCP; multi-graph; **no TLS, no persistence/backups**; stopped after 1 day inactive, deleted after 7. Fine for a ≤100 MB demo (1000 tenant graphs ≈0.4–0.57 GiB would NOT fit → ≤ ~150 tiny graphs; 100k-node scale demo ≈70 MB used_memory is borderline). |
| **Render free web service** | Docker supported, no card, 512 MB RAM / 0.1 CPU, spins down after 15 min idle (~1 min wake), ephemeral disk, 750 h/mo. Too small to also host FalkorDB at scale; OK for API/UI. falkordblite needs glibc ≥2.39 → use Docker base Ubuntu 24.04/Debian 13 or `falkordb/falkordb`. |
| Railway | $5 trial / 30 days reportedly no card; FalkorDB publishes templates. |
| ✗ Hugging Face Docker Spaces (paid plan), ✗ Koyeb, Northflank, Fly, Oracle (card) | |
**[J] Recommendation:** UI/API on Render free (keep-alive ping), DB on FalkorDB Cloud Free (connect with host/port/password; no TLS), **plus complete local instructions as mandatory fallback** (rules allow local-setup instead of live deploy). Record the demo video locally.

## 10. File map
`start-falkordb.sh`, `snapshot_restart_test.sh`, `bin/README.md`, `examples/py/{common,01..11,bisect*}.py`, `examples/node/01_basic.mjs`, `examples/mcp/{server_py.py,client_smoke.py,opencode.json,ts/*,official/*}`, `bench/*` (all raw outputs), `docs_cache/*.md` (offline copies of the official docs), `GOTCHAS.md`.
