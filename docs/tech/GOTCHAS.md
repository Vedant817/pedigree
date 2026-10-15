# FalkorDB gotchas (found while building the provenance layer). [V]=reproduced here, [D]=documented only.

## Operational traps
1. **Run with limits or one bad write kills the server [V].** Defaults `TIMEOUT_MAX/TIMEOUT_DEFAULT/QUERY_MEM_CAPACITY = 0`. Without TIMEOUT_MAX a write ignores per-query timeout; a 50k×50k cartesian `SET` reached 6.3 GB and the OOM killer took redis-server. Start with `TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`. A timeout above TIMEOUT_MAX errors.
2. **Never `DROP INDEX` an index backing a constraint [V on 4.18.3 AND 4.22.1].** It is rejected ("Index supports constraint") but poisons the schema: every later BGSAVE child segfaults (`RdbSaveGraphSchema_v19`), `rdb_last_bgsave_status:err`, Redis then blocks all writes (MISCONF stop-writes-on-bgsave-error). Only `FLUSHALL` cleared it. Repro: examples/py/bisect5.py. Workaround: don't do it (or `config set stop-writes-on-bgsave-error no` as a stopgap [untested]).
3. **`DUMP`/`RESTORE` of a graph key crashes 4.18.3 [V]** (assert in `BufferSerializerIOv2_ReadUnsigned`). Fixed in 4.22.1 (RESTORE worked on a 20k-node graph [V]). Use `GRAPH.COPY`.
4. **Index builds are async [V].** Vector `queryNodes` during "UNDER CONSTRUCTION" raises "Invalid arguments for procedure" — poll `CALL db.indexes()` until OPERATIONAL (`common.wait_indexes`). Unique constraints also start PENDING and need an exact-match index first ("missing supporting exact-match index"). MANDATORY constraint on already-violating data ends FAILED.
5. **Path enumeration blowup [V].** `[:R*1..k]` enumerates paths, not nodes: layered DAG width 8: k=5 46 ms, k=6 340 ms, k=7 2.75 s, then timeout; 105k dense graph: k=8 2.1 s, k=10 timeout. Use `algo.BFS` (0.6 ms in the same test) or bound depth + `RETURN DISTINCT`. Diamonds create duplicate rows without DISTINCT.
6. **`algo.BFS` quirks [V].** Follows only *outgoing* edges of ONE type (hence mirrored FEEDS edges); excludes the start node; node order undefined; `nodes` is a list you `UNWIND`.
7. **Atomicity [V].** One query = atomic (UNWIND batches, multi-clause writes, constraint violation rolls back everything). **MULTI/EXEC is not**: commands before a failing one persisted. Put the whole cascade in one query.
8. **Long write stalls readers [V].** A 0.5–0.7 s cascade made same-graph reader p95 5→452 ms, and a reader on another graph also stalled (inferred from throughput; mechanism unverified). Writes are serialised per graph (~5.3k/s). Bound/chunk big cascades; keep the UI read path tolerant.
9. **Memory never shrinks [V].** RSS stays ~355 MiB after deleting a 100k-node graph (allocator); graph deletion is async so `used_memory` immediately after delete is misleading. ~0.4 MiB per empty-ish graph (570 KiB with an index) → thousands of tenants cost GBs; Cloud Free cap is 100 MB.
10. **`GRAPH.PROFILE` via python `g.profile()` omits stats [V]** — use `execute_command("GRAPH.PROFILE", ...)`.
11. **Vector search [V].** `score` is a distance (lower = better); post-filtering after ANN → fewer than k rows (asked 10 got 4): over-fetch then filter; vectors must be wrapped `vecf32()` in Cypher; dims 1–4096.
12. **Docker `latest` is now a different engine [D].** 6.0.x is Rust; A*/CCH not ported; DUMP/RESTORE etc. may differ. Pin a tag; I could only run 4.18.3 and 4.22.1.
13. **falkordblite needs glibc ≥ 2.39 [V]** (old distros / many PaaS native runtimes fail) — use a Docker base ≥ Ubuntu 24.04. Release `.so` needs `chmod +x`.
14. **Free deploy [D]:** Cloud Free = 100 MB, no TLS, no persistence, stopped after 1 day idle/deleted after 7 → seed on startup; Render free sleeps after 15 min (≈1 min wake).
15. **Shared box note [V]:** `sleep >30 s` in the Shell tool backgrounds the command; use `python -u` for logs.

## Cypher dialect differences
- `shortestPath(...)` only inside `WITH/RETURN`, both endpoints already bound [V]. `allShortestPaths` only in `MATCH`, and needs `MATCH (a),(b) WITH a,b MATCH p=allShortestPaths((a)-[*]->(b))` ("Source and destination must already be resolved") [V].
- Var-length relationship variable is **not a list**: `all(e IN r WHERE ..)` errors; filter inline `-[:R*1..3 {w:1}]->` or use `relationships(p)` [V].
- Property values must be primitives or arrays — **no map properties** ("Property values can only be of primitive types or arrays"); store `tojson()` strings [V].
- No `datetime()`; use `timestamp()` (epoch ms), `localdatetime()`, `date()`, `duration`; `date.transaction()` is UTC-based [V]. `randomuuid()`, `tojson()`, `vecf32()`, `vec.cosineDistance()` exist (144 functions in 4.18.3).
- No CDLP/louvain/leiden/triangleCount (only `labelPropagation`, `WCC`, `pageRank`, `betweenness`, `MSF`) [V]. No APOC, no regex operator, no UDFs [D].
- Deleting a node deletes its edges implicitly [V]. `SET` of a property is reported under "Properties removed" in stats [V].
- [D] Unreferenced relationship aliases are only existence-checked, so counts can be wrong → reference/return the alias. `LIMIT` does not stop eager CREATE/SET/DELETE/MERGE. Indexes don't serve `<>`. No aggregates in pattern comprehensions. No parameters for LIMIT/SKIP (per MCP README).

## SDK / tooling
- **Python `mcp` 2.x renamed FastMCP → `MCPServer`** (`mcp.server.mcpserver`); `mcp.server.fastmcp` raises ModuleNotFoundError; transport args move to `run()` [V]. Pin `mcp<2` if copying older tutorials.
- **`graphiti-core[falkordb]` 0.30.2: `import graphiti_core` fails (`No module named httpx`)** until `pip install httpx` [V]. **`cognee` ≈1.5 GB; `graphrag-sdk` needs g++ for hnswlib and torch via gliner** [V] — skip on small disks.
- **Official `@falkordb/mcpserver` has no tenant isolation** (any graphName accepted; includes `delete_graph`) [V] — build your own tenant-scoped server for the product.
- TypeScript MCP SDK: stay on `@modelcontextprotocol/sdk` 1.32.1 (v1 API) unless you test the v2 split packages [D].
- Node client: `TIMEOUT` option key is uppercase; results are `.data` / `.metadata` [V].

## Added while specifying Pedigree (2026-10-15, FalkorDB 4.22.1 unless noted) - all [V], scripts in examples/py/12_*.py and 13_*.py
16. **Silent parent loss:** `UNWIND $parents AS pid MATCH (p:Node {id:pid}) ...` drops ids that do not exist without error -> validate with a read first. **`UNWIND []` yields zero rows**, so a later `SET` in the same query never runs (the preceding `CREATE` still happened) -> use a separate query for the 0-parent case.
17. **Graph-name ACL prefixes:** `~ped_a*` also matches tenant `ab`. Use delimiter names `ped:<tenant>` with tenant `[a-z0-9]{3,24}` and patterns `~ped:abc ~ped:abc:wi:*`. The Python client runs `INFO` on connect -> ACL users need `+info`. `%R~` selectors did not allow `GRAPH.RO_QUERY` (denied); `~pattern` works. `GRAPH.LIST` exposes every graph name to a user with `+graph.list`.
18. **`exists((n)-[:R]->(:L))` in WHERE fails** ("Unable to resolve filtered alias"); use `OPTIONAL MATCH` + `count`. `LIMIT $k` with a parameter works on 4.22.1. `any()`, `reduce()`, `coalesce(arr, [])`, `x IN $list`, array property assignment all work.
19. **Never run two servers on one `--dir`** (AOF/RDB clash). `start-falkordb.sh` now takes `DATA_DIR`.
20. **Multi-label nodes** (`:Node:Memory`) work with a single `Node(id)` index and unique constraint.
