# 09 - TECH CHEATSHEET (condensed; full: tech/TECH_REFERENCE.md, tech/GOTCHAS.md)
Tags: **[V]** verified by running on the research box 2026-10-15 (Linux x64, Python 3.13, Node 20, glibc >= 2.39, no Docker); **[D]** docs only; **[U]** unverified - test first. Event facts: Oct 15 12:01 AM IST -> Oct 18 11:59 PM IST; FalkorDB must be central; README needs setup + graph data model + the Cypher/algorithms; demo video; live deploy preferred else full local instructions.

## A. Run FalkorDB without Docker, pinned to v4.22.1 [V]
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install falkordblite==0.10.0 falkordb==1.8.0 "mcp>=2,<3"   # wheel ~34-36 MB; supplies redis-server 8.6.2 (+ FalkorDB 4.18.3 .so we do NOT ship)
bash scripts/fetch-falkordb.sh      # curl -L -o bin/falkordb-4.22.1-x64.so https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.1/falkordb-x64.so && chmod +x bin/*.so   (51 MB; forget chmod => server aborts)
FALKOR_SO=$PWD/bin/falkordb-4.22.1-x64.so PORT=6379 DATA_DIR=./data bash scripts/start-falkordb.sh   # loads module into the wheel's redis-server
```
`start-falkordb.sh` env: `PORT` (6379), `DATA_DIR` (default ./data - **use a different dir per server!** two servers on one dir corrupt AOF), `FALKOR_SO`, `FALKOR_ARGS` (default `TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824` = **mandatory**; defaults are 0=unlimited and one runaway write OOM-killed the server at 6.3 GB [V]). Verify: `redis-cli MODULE LIST` -> `graph ver 42201`. glibc >= 2.39 needed for the wheel (use Ubuntu 24.04+ images). Docker if available: `docker run -p 6379:6379 -v falkor:/var/lib/falkordb/data falkordb/falkordb:v4.22.1` [D]. **Never `latest`** (Rust 6.0.x engine, not run here) [D]. License SSPLv1.
Process hygiene on the shared box: start servers with `setsid nohup ... &`; `pkill -f "redis-server.*PORT"`; wait for the port to free before restarting.

## B. Python client (falkordb 1.8.0) [V]
```python
from falkordb import FalkorDB
db = FalkorDB(host="localhost", port=6379, username=None, password=None)   # client runs INFO on connect => ACL users need +info
g = db.select_graph("ped:acme")                    # created lazily on first write
r = g.query("MERGE (n:Node {id:$id}) RETURN n", {"id":"x"}, timeout=5000); r.result_set; r.run_time_ms
g.ro_query(...); g.copy("ped:acme:wi:ab12cd34"); g.delete(); db.list_graphs()
db.connection.execute_command("GRAPH.CONSTRAINT","CREATE","ped:acme","UNIQUE","NODE","Node","PROPERTIES","1","id")
db.connection.execute_command("GRAPH.PROFILE", name, query)     # g.profile() omits stats
```
`g.delete()` on a missing graph raises ResponseError (wrap). Python `ResponseError`/`NoPermissionError` for ACL denials ("No permissions to access a key").

## C. Cypher dialect rules that bit us [V unless noted]
- **Multi-label nodes work** (`CREATE (:Node:Memory ...)`, `MATCH (n:Node {id:$i})` uses the `Node(id)` index).
- Index build is **async** - poll `CALL db.indexes()` until OPERATIONAL. Unique constraint needs the exact-match index first, starts PENDING; **never DROP an index backing a constraint** (poisons BGSAVE).
- `MATCH (p:Node {id:pid})` after `UNWIND $ps AS pid` **silently drops missing parents**; `UNWIND []` yields no rows so later `SET` never runs -> validate parents first; separate orphan query.
- `algo.BFS(start, depth, 'REL')`: outgoing edges of ONE type; excludes the start node; unordered `nodes`; `-1` = unbounded. Mirror edges (`FEEDS`) for descendants. 12 ms for ~65k affected nodes on a 105k-node dense DAG.
- Var-length `*1..k` enumerates paths: k=8 2.1 s, k=10 timeout (dense 105k graph). Use BFS or depth <= 3 + `RETURN DISTINCT`.
- `shortestPath((a)-[:R*..n]->(b))` only in `WITH/RETURN` with both ends bound; `allShortestPaths` only in `MATCH` after `WITH a,b`.
- No map properties (primitives/arrays only; use `tojson`); no `datetime()` (use `timestamp()`); `LIMIT $k` **works** with a parameter on 4.22.1 [V] (older notes said no).
- `exists((n)-[:R]->(:L))` in WHERE **fails** on 4.22.1 ("Unable to resolve filtered alias") [V]; use `OPTIONAL MATCH ... WITH n, count(x) AS c WHERE c > 0`.
- List helpers that work: `any(t IN list WHERE ...)`, `reduce(acc = init, x IN xs | acc + [...])`, `coalesce(arr, [])`, `x IN $param_list`, `CASE WHEN`. `n.arr = $list` stores arrays.
- Procedures present: `algo.BFS, MSF, SPpaths, SSpaths, WCC, betweenness, labelPropagation, pageRank` (+ `AStar, HarmonicCentrality, maxFlow, db.idx.cch.query` on 4.22.1). `CALL algo.pageRank('Node','DERIVED_FROM') YIELD node, score` [V]. No louvain/leiden/CDLP/triangleCount, no APOC, no regex operator, no UDF.
- Vector: `CREATE VECTOR INDEX FOR (n:L) ON (n.emb) OPTIONS {dimension:384, similarityFunction:'cosine'}`; `vecf32([...])`; score = **distance**; post-filter => over-fetch. Full-text: `db.idx.fulltext.createNodeIndex('L','text')`. (Optional for Pedigree.)
- Unreferenced relationship aliases only existence-checked [D]; `LIMIT` doesn't stop eager writes [D].

## D. Consistency and concurrency [V]
- One query = atomic (UNWIND batches, multi-clause writes, constraint violation rolls back). **MULTI/EXEC is NOT atomic.** CAS inside one query works: `MATCH (m {id:$i, v:$old}) SET m.v=$new RETURN count(m)`.
- Writes serialize per graph (~5.3k/s); ~9-10k/s across several graphs; reads scale to ~1.6k q/s with 8 readers. A 0.5-0.7 s write stalled same-graph readers (p95 5 -> 452 ms); another graph's reader stalled in one run (mechanism unverified) => chunk writes <= 2000 ids.
- Cascade write cost ~8 us/node (dense 105k: p50 546 ms for 65k nodes in one query).
- `GRAPH.COPY src dst`: atomic, keeps indexes, errors if dst exists; 20k nodes ~165 ms (54-190 ms in our proto) ; `DUMP/RESTORE` crashes 4.18.3, fixed 4.22.1 - still prefer COPY.
- Persistence: AOF everysec + RDB; `kill -9` + restart kept data (<= ~1 s of writes at risk). Memory: ~0.4 MiB per near-empty graph (570 KiB with an index); 1000 graphs ~0.41 GiB; RSS never shrinks after deletes.

## E. Per-tenant ACL isolation [V examples/py/13_acl_tenant_isolation.py]
```
ACL SETUSER t_abc on >pw resetkeys ~ped:abc ~ped:abc:wi:* -@all +info +ping +graph.query +graph.ro_query +graph.explain +graph.delete +graph.copy +graph.constraint
```
Cross-graph read/write/copy denied ("No permissions to access a key"). `%R~` selectors did not allow `GRAPH.RO_QUERY` here - use `~pattern`. Tenant ids `[a-z0-9]{3,24}` so `~ped:abc` cannot match `ped:abcd`. `GRAPH.LIST` returns ALL graph names to a user holding `+graph.list` (omit it). ACL on FalkorDB Cloud Free **[U]**.

## F. MCP (Python SDK 2.x) [V in tech/examples/mcp]
```python
from mcp.server.mcpserver import MCPServer          # mcp>=2 (mcp<2: from mcp.server.fastmcp import FastMCP)
mcp = MCPServer("pedigree")
@mcp.tool()
def revoke(node_id: str, reason: str, dry_run: bool = True) -> dict: ...
mcp.run("streamable-http", host="127.0.0.1", port=8765)    # v2: transport args go to run(); endpoint /mcp ; stdio: mcp.run("stdio")
```
Never print to stdout in stdio mode. Client: `from mcp import Client, StdioServerParameters`; smoke: `tech/examples/mcp/client_smoke.py`. TS SDK: `@modelcontextprotocol/sdk` 1.32.1 (v1 API). ASGI mounting + bearer middleware **[V]** `tech/examples/mcp/mount_in_fastapi.py` (needs lifespan with `mcp.session_manager.run()`); `TokenVerifier`/`AuthSettings` exist but **[U]**. Official `@falkordb/mcpserver` (generic Cypher passthrough, **no tenant isolation**, has `delete_graph`) = baseline only.

## G. OpenCode [D, https://opencode.ai/docs/agents/ , /plugins , /mcp-servers; read 2026-10-15]
- Agents: `.opencode/agents/<name>.md`; frontmatter `description` (req), `mode`, `model`, `temperature`, `steps`, `permission`; permission values `allow|ask|deny` or glob maps (last match wins); `permission.task` restricts subagents; `tools:` deprecated.
- Plugins: `.opencode/plugins/*.ts|js`; `export const X = async ({project, client, $, directory, worktree}) => ({ "tool.execute.before": async (input, output) => {...}, "tool.execute.after": ..., event: async ({event}) => {...} })`; throwing in `before` blocks (official `.env` example: `input.tool==="read" && output.args.filePath.includes(".env")`). Events: `session.created|idle|updated|error`, `file.edited`, `message.updated`, `permission.asked`, ... `after` payload shape **[U]** (log it).
- MCP: `opencode.json` `"mcp": {"name": {"type":"remote","url":"http://127.0.0.1:8000/mcp","oauth":false,"headers":{"Authorization":"Bearer {env:PEDIGREE_TOKEN}"},"enabled":true,"timeout":10000}}`; local: `"type":"local","command":["python","-m","pedigree.cli","mcp","--transport","stdio"],"environment":{...}`. Tools appear as `<server>_<tool>`.

## H. Claude Code hooks [D, https://docs.claude.com/en/docs/claude-code/hooks ; read 2026-10-15]
- Config in `.claude/settings.json` (project, committable), `.claude/settings.local.json`, `~/.claude/settings.json`. Shape: `{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"${CLAUDE_PROJECT_DIR}/.claude/hooks/x.sh","timeout":10}]}]}}`; handler types: `command`, `http` (`url`, `headers`, `allowedEnvVars`, `onFailure`), `mcp_tool` (`server`, `tool`, `input`), prompt/agent.
- Inputs: common `session_id, transcript_path, cwd, permission_mode, hook_event_name`; `UserPromptSubmit` adds `prompt`; `PreToolUse` adds `tool_name, tool_input, tool_use_id` (file paths absolute); `PostToolUse` adds `tool_response, duration_ms`.
- Block: stdout JSON `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}` exit 0 (exit code 2 is documented to block too - **[D] documented per event, verify in the Phase 0 spike**; prefer the JSON form). **A timed-out command/http hook does NOT block**; set `"onFailure":"block"` (v2.1.295+) to fail closed. PostToolUse can add context (`additionalContext`) or replace output (`updatedToolOutput`).
- Matcher `*` and regex alternation semantics, `permissionDecision:"ask"` **[U]** - verify in the docs sections "Matcher patterns" / "PreToolUse decision control".

## I. Free, no-card services (limits move; confirm in your console) 
Gemini API (AI Studio): free tier, limits per model/project visible in AI Studio, daily reset midnight Pacific, free-tier data may be used by Google. Groq: gpt-oss-120b/20b, qwen: 30 RPM, 1K RPD, 8K TPM, 200K TPD (https://console.groq.com/docs/rate-limits). OpenRouter `:free`: 20 RPM, 50 RPD (secondary). Mistral free: unverified. Cerebras needs a payment method (avoid). Embeddings: `fastembed==0.9.0` + `BAAI/bge-small-en-v1.5` (384-d, ~65 MB cache, no torch) [V]. Pedigree's core needs **no LLM**.
Deploy: FalkorDB Cloud Free (100 MB, no card, **no TLS**, no persistence, stops after 1 day idle, deleted after 7 [D docs.falkordb.com/cloud/tiers/free]); Render free web service (Docker OK, 512 MB, sleeps after 15 min [D render.com/docs/free]). Local fallback is mandatory.

## J. Disk-budget rules
No torch/transformers/GraphRAG-SDK/Cognee (1.5 GB). `.venv` ~160 MB with falkordblite+mcp; `.so` 51 MB (git-ignored, fetched by script). Do not commit `bin/`, `data/`, `.venv/`, `browser-src/`, `docs_cache/`.
