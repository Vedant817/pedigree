# 01 - PEDIGREE: product specification

> **One-liner:** git blame and git revert for what an AI agent believes. Pedigree records, out-of-band, where every memory, rule and action of a coding agent came from, stores that lineage in FalkorDB (one graph per tenant), and lets you revoke a bad source, see exactly what it contaminated (down to the commit), keep what is independently supported, and gate risky actions before they run.

Tags used in this pack: **[V]** verified by running it on 2026-10-15; **[D]** from official docs only; **[J]** judgement; **[U]** unverified, test first.

## 1. Problem (with sources)
1. Agents now keep persistent memory and read rules/skills/MCP tool descriptions that steer later behaviour. Poisoned or wrong content in any of these persists across sessions.
   - OWASP Top 10 for Agentic Applications 2026 lists *Memory & Context Poisoning* (ASI06): https://genai.owasp.org/download/52117/
   - Rehberger: a malicious document plants conditional instructions; a later "yes" makes Gemini write attacker-chosen entries to long-term memory: https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/ ; ChatGPT SpAIware persistent exfiltration: https://embracethered.com/blog/posts/2024/chatgpt-macos-app-persistent-data-exfiltration/
   - MINJA: query-only memory injection, paper reports 98.2% injection / 76.8% attack success in its setting: https://arxiv.org/abs/2503.03704 ; AgentPoison: https://arxiv.org/html/2407.12784
   - Coding-agent supply chain: Rules File Backdoor (hidden Unicode in Cursor/Copilot rules): https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents ; MCP tool poisoning / rug pulls: https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks
2. Defences are mostly *write-time detection* (e.g. OWASP Agent Memory Guard https://owasp.org/projects/agent-memory-guard, MCP-Scan https://invariantlabs.ai/blog/introducing-mcp-scan). Detection eventually fails or arrives late. Then the question is **"what did we already believe, and do, because of it?"** Nobody can answer it today: vector stores keep no derivation, and Graphiti's `remove_episode` only removes edges whose first provenance is that episode (https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py, https://github.com/getzep/graphiti/pull/261).
3. Multi-tenant agent memory fails silently under concurrency: Graphiti issues #1331 (open) and #1676 (closed 2026-09-08) on FalkorDB cross-group contamination: https://github.com/getzep/graphiti/issues/1331 , https://github.com/getzep/graphiti/issues/1676
**Who suffers:** engineers and teams running Claude Code / OpenCode / Cursor with persistent memory files, rules, skills and MCP servers; platform teams hosting shared agent memory for many tenants.

## 2. What Pedigree IS and IS NOT
**IS**
- A **lineage ledger** (source -> session -> memory -> action -> artifact/commit) captured by hooks/plugins **outside the model's control**.
- A **containment engine**: revoke a source/memory, quarantine first (barrier), compute the final tainted set with **independent-support preservation**, list affected actions and **irreversible** external effects, never hard-delete.
- A **pre-action gate** (allow / reverify / block, with the lineage path as the reason) exposed as an MCP tool and a hook.
- **Integrity + confidentiality labels** propagated along derivation edges (information-flow control for persistent memory).
- A **tenant-isolated service**: one FalkorDB graph per tenant, bearer-token auth, per-tenant DB ACL users as defence in depth, input limits, query timeouts, parameterised Cypher only.
- A **reproducible evaluation harness** (committed scripts, seeded) and an attack-scenario suite.
**IS NOT**
- Not a prompt-injection *preventer* or a detector. "Which source is bad" is an input (human, scanner, alert). We contain, explain, revert.
- Not a sandbox. The bash-command risk classifier is a heuristic.
- Not an undo for external effects already taken (a push that others pulled). We **list** them.
- Not a general RAG/chat memory. Retrieval quality is out of scope (we expose `status` so retrievers can exclude quarantined/tainted nodes).
- Not novel as an algorithm (see section 3).

## 3. Honest differentiation
| Work | Overlap | What Pedigree adds (as a shipped system) |
|---|---|---|
| PACMI https://arxiv.org/html/2610.05732v1 | typed dependency graph + cascading invalidation, validity states, history preserved | real capture (edges are not hand-annotated), live adapters, gate, multi-tenant service, measured baselines |
| MemoRepair https://arxiv.org/abs/2605.07242 | barrier-first withdrawal, repair of stale memory; shows 1% dropped edges -> 17.7% leak (https://arxiv.org/pdf/2605.07242v1/__stdout.txt) | we **measure capture fidelity** (E2), choose conservative session-window capture, report over-approximation; barrier + fixpoint is implemented on a real graph DB |
| MAP-Graph https://arxiv.org/abs/2608.10509 | typed execution graph, ancestry trust, action gate with Allow/Block/Reverify/Redact/AskUser | research prototype; we ship MCP + hooks + service + eval, add independent-support preservation and per-tenant isolation tests |
| CaMeL https://arxiv.org/abs/2503.18813 / FIDES https://arxiv.org/abs/2505.23643 | information-flow labels (integrity + confidentiality), block violating tool calls | they are per-run and in-process; we persist the flow graph across sessions/agents as queryable infrastructure |
| Graphiti/Zep https://github.com/getzep/graphiti | temporal edges, `remove_episode`, `group_id` tenancy, FalkorDB backend | we trace *derived beliefs and actions* and have a tenant-isolation conformance suite motivated by its FalkorDB bugs |
| Neo4j Agent Memory https://neo4j.com/labs/agent-memory/ | reasoning traces, `:TOUCHED` audit edges | audit is read-only there; we revoke, contain, gate |
| mesa-dot-dev/agentblame https://github.com/mesa-dot-dev/agentblame | "which lines were written by AI" attribution for git | different object: they attribute *code lines to AI*, we track *beliefs/rules/sources -> actions* |
| In-event: kintsugi (Itz-Agasta), undograph (Tejas-Sands), lineage (Vaibhaav-Tiwari) | same family (provenance + undo/repair on FalkorDB) | as above; **be generous and factual about them**. See research/06-competitor-census.md. Re-read their repos on Sat/Sun morning. |
**Claimed novelty (and only this):** engineering + evaluation: out-of-band capture from real coding-agent runtimes; independent-support preservation measured against baselines; joint integrity/confidentiality labels; tenant-isolation/concurrency suite on FalkorDB; reproducible attack zoo.

## 4. User stories
1. *Contain:* "A web page I let the agent read was malicious. Show everything it influenced and revert it." -> `revoke` dry-run shows 31 nodes incl. 2 file edits, 1 commit, 1 push; confirm; quarantine is instant; revert list printed.
2. *Keep what's solid:* "Two memories came from that page but are also supported by our docs. Don't throw them away." -> status `preserved` with the supporting source shown.
3. *Gate:* "Before the agent runs `git push`, check whether anything it relied on is tainted or confidential." -> `check_action` returns `block` + path.
4. *Blame:* "Why does the agent believe X?" -> `blame` returns the ancestry graph and the shortest path to each root.
5. *Isolation:* "Tenant A's agent must never read or write tenant B's lineage, even under concurrent load."
6. *Audit:* "Which sources are load-bearing (most things derive from them)?" -> PageRank/descendant counts.
7. *What-if:* "If I revoke these three sources, what breaks?" -> simulate on a `GRAPH.COPY`.
8. *Honesty:* "Does anything depend on id Z?" for an id never recorded -> `not_in_graph` (not "no impact").

## 5. Data model (per-tenant graph)
**Graph name:** `ped:<tenant>` with tenant id `^[a-z0-9]{3,24}$`. What-if copies: `ped:<tenant>:wi:<8 hex>`. Checkpoints: `ped:<tenant>:ck:<name>`. [V: names with `:` work; ACL patterns `~ped:abc` and `~ped:abc:wi:*` isolate `abc` from `abcd` (examples/py/13_acl_tenant_isolation.py, bench/acl_tenant_isolation_v4221.txt)]. Do **not** use underscore/`*` prefix patterns like `ped_a*` (they also match tenant `ab`).
**Labels:** every node has `:Node` plus one of `:Source :Memory :Action :Session :Agent :Revocation`. One index + one unique constraint on `Node.id` serve all lookups (multi-label create/match verified [V]).
```cypher
CREATE INDEX FOR (n:Node) ON (n.id)                     -- async: poll CALL db.indexes() until OPERATIONAL
GRAPH.CONSTRAINT CREATE ped:<t> UNIQUE NODE Node PROPERTIES 1 id   -- needs the exact-match index first; starts PENDING; NEVER DROP that index afterwards (GOTCHAS #2)
CREATE INDEX FOR (n:Memory) ON (n.artifact_key)  CREATE INDEX FOR (n:Action) ON (n.artifact_key)   -- cross-session file lineage lookup
CREATE INDEX FOR (n:Revocation) ON (n.state)   -- optional
```
**Node properties** (no map properties allowed; arrays of primitives only; store JSON as string via `tojson`):
| Label | Properties |
|---|---|
| all | `id` (string, unique, <=128 chars), `tenant` (denormalised for the isolation audit), `status`, `created_at` (ms, `timestamp()`) |
| Source | `kind` in `user_prompt|file|web|tool_output|rules_file|mcp_tool_desc|human|other`, `uri` (<=512), `content_hash` (sha256 hex), `title` (<=160), `integrity` (`trusted|untrusted`), `low_integrity` (bool; true iff untrusted), `conf` (array of tags), `conf_eff` (= `conf` for sources), `status` in `ok|revoked`, `revoked_at`, `reason` |
| Memory | `mkind` in `fact|summary|decision|preference|procedure|rule`, `text` (<=2000 chars; **hash-only mode** stores `''` + `content_hash`), `artifact` (path), `artifact_key` (`<path>@<sha256 after write>`), `content_hash`, `conf`, `conf_eff`, `low_integrity`, `unanchored` (bool), `status` in `ok|quarantined|tainted|preserved|revoked`, `taint_parent` (id of one tainted parent = blame pointer), `agent_id`, `session_id` |
| Action | `tool`, `summary` (<=300), `args_hash`, `effect` in `reversible|irreversible|unknown`, `risk` in `low|medium|high`, `artifacts` (array: paths/commit shas/URLs), `artifact_key` (for write/edit: `<path>@<sha256 after write>`), `decision` (last gate verdict), `status` in `ok|quarantined|tainted`, `taint_parent`, `session_id` |
| Session | `runtime` in `claude_code|opencode|mcp|other`, `started_at`, `agent_id` |
| Revocation | `root_id`, `reason`, `kind` in `revoke|supersede`, `state` in `running|done|failed`, `n_tainted`, `n_preserved`, `n_actions`, `started_at`, `finished_at` |
**Edges**
| Edge | Meaning | Props |
|---|---|---|
| `(child:Memory|Action)-[:DERIVED_FROM]->(parent:Source|Memory|Action)` | child was derived from / relied on parent. An **Action may be a parent** only through the artifact-hash link (a later read of a file whose `path@sha256` equals an earlier write Action's `artifact_key`), which is how taint flows through code edits across sessions. | `rel` (`derive|rely`), `via` (`cite|session_read|agent_reported|hook`) |
| `(parent)-[:FEEDS]->(child)` | **mirror of DERIVED_FROM** so `algo.BFS` (outgoing, one type) can walk descendants. Always written in the same query. | - |
| `(m:Memory)-[:CORROBORATED_BY]->(s:Source)` | independent support (targets are Sources only, so no cycles) | `by` (`agent|human|scanner`) |
| `(a:Agent)-[:WROTE]->(m:Memory)`, `(sess:Session)-[:READ]->(n:Source|Memory)`, `(sess)-[:PERFORMED]->(a:Action)` | context / read window | `at` |
| `(new:Memory)-[:SUPERSEDES]->(old:Memory)` | versioning (P2) | - |
Rules: DAG by construction (edges only to already-existing nodes at creation time); nodes are never hard-deleted (except tenant wipe); `status` is the only mutable lifecycle field.
**Why mirror edges:** `algo.BFS` follows only outgoing edges of ONE type, excludes the start node, returns unordered node lists [V, GOTCHAS #6]; var-length `*1..k` enumerates *paths* and blows up on dense DAGs (k=8 2.1 s, k=10 timeout on 105k nodes) [V]. BFS: 12 ms for ~65k affected nodes [V].

## 6. Algorithms and Cypher (all patterns verified in `tech/examples/py/12_pedigree_core.py` on 4.18.3 and 4.22.1 [V])
All Cypher lives in `src/pedigree/db/queries.py` as module-level constant strings with `$params`. **Never** build Cypher with f-strings from user input. The only interpolated token is the node label from a fixed allow-list constant.

### 6.1 Ingest (each op = ONE atomic query; never MULTI/EXEC)
Validate parents first (a missing parent is silently dropped by `MATCH` [V] and an empty `UNWIND` skips the `SET` [V]):
```cypher
// Q_FIND_IDS (read)
MATCH (n:Node) WHERE n.id IN $ids RETURN n.id, n.status
```
If `len(found) != len(set(parents))` -> error `not_in_graph` listing missing ids. Then:
```cypher
// Q_CREATE_MEMORY_WITH_PARENTS (>=1 parent) -- inherits flags atomically
CREATE (c:Node:Memory {id:$id, tenant:$tenant, text:$text, mkind:$mkind, artifact:$artifact, content_hash:$hash,
        agent_id:$agent, session_id:$session, conf:$conf, status:'ok', unanchored:false, created_at:timestamp()})
WITH c UNWIND $parents AS pid MATCH (p:Node {id:pid})
MERGE (c)-[d:DERIVED_FROM]->(p) SET d.rel=$rel, d.via=$via
MERGE (p)-[:FEEDS]->(c)
WITH c, collect(p) AS ps
SET c.low_integrity = any(p IN ps WHERE p.low_integrity = true),
    c.conf_eff = reduce(acc = c.conf, p IN ps | acc + [t IN coalesce(p.conf_eff, []) WHERE NOT t IN acc]),
    c.status   = CASE WHEN any(p IN ps WHERE p.status IN ['revoked','tainted','quarantined']) THEN 'quarantined' ELSE 'ok' END
RETURN c.status, c.low_integrity, c.conf_eff, size(ps)
// Q_CREATE_MEMORY_ORPHAN (0 parents): same CREATE with unanchored:true, low_integrity:true, conf_eff:$conf, no UNWIND
```
A child created under a quarantined/tainted/revoked parent is **born quarantined** (race-safe barrier, see 6.3). Actions use the same pattern with label `Action` and `rel='rely'`. `CORROBORATED_BY`:
```cypher
MATCH (m:Memory {id:$m}), (s:Source {id:$s}) MERGE (m)-[r:CORROBORATED_BY]->(s) SET r.by=$by RETURN m.id, s.id
```
Corroboration is **lazy**: the write adds the edge only and does not touch any `status`. A newly
corroborated memory stays `tainted` until the next recompute (the next `revoke`/`reinstate`), which
re-reads the support edges and re-derives the map; support is therefore effective as of the last
recompute. Making `corroborate` recompute is a separate behavioural change, not implied here
(ADR-015).
Session read window: `MATCH (se:Session {id:$sess}), (n:Node {id:$n}) CREATE (se)-[:READ {at:timestamp()}]->(n)`; read-window lookup for actions: last K (default 50) distinct READ targets, `ORDER BY r.at DESC LIMIT $k`.

### 6.2 Impact preview (read-only) and discovery
```cypher
// Q_DESCENDANTS: BFS over FEEDS; excludes the start node; unordered
MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes UNWIND nodes AS n RETURN n.id, labels(n), n.status
// Q_ANCESTORS
MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'DERIVED_FROM') YIELD nodes UNWIND nodes AS n RETURN n.id, labels(n), n.status
```
`depth=-1` is unbounded [V]; use 12 as the product default and report `truncated` if the frontier is non-empty at the limit.

### 6.3 Revoke: barrier -> fixpoint -> support-preserving final status -> verify (the core algorithm)
Semantics. Let R be the set of revoked roots (Sources or Memories). Let C = descendants of R via FEEDS. For m in C processed in topological order:
`bad(m)` = any DERIVED_FROM parent that is in R or finally `tainted`. If `bad(m)` is empty -> `ok`. Else if m has a **healthy** CORROBORATED_BY source -> `preserved` (retrievable, flagged with the supporting source); a **healthy** source here means a `CORROBORATED_BY` source whose **status is `ok`** — the edge's `by` (agent/human/scanner) and the source's `integrity` do not enter the status recurrence. Else -> `tainted` with `taint_parent` = one bad parent. Note a node whose only bad parent became `preserved` is simply `ok`.
Steps (per tenant, under an in-process per-tenant lock; **idempotent and crash-recoverable**):
1. **Barrier (one atomic query):**
```cypher
// Q_REVOKE_ROOT -- CAS: only flips if not already revoked; empty result => idempotent no-op
MATCH (r:Node) WHERE r.id=$id AND r.status <> 'revoked' AND (r:Source OR r:Memory)
SET r.status='revoked', r.revoked_at=timestamp(), r.reason=$why RETURN r.id
CREATE (:Node:Revocation {id:$rid, tenant:$tenant, root_id:$id, reason:$why, kind:$kind, state:'running', started_at:timestamp()})
```
2. **Quarantine fixpoint:** loop (max 10): `roots = MATCH (r:Node {status:'revoked'}) RETURN r.id`; discover C by `Q_DESCENDANTS` from each root; `todo` = members with status `ok|preserved`; if none -> break; else write in chunks of <= 2000 ids: `UNWIND $ids AS i MATCH (n:Node {id:i}) SET n.status='quarantined'`. Once the loop sees no `ok|preserved` member, every new child will be born quarantined (6.1), so the barrier holds. Safe-by-default: if the process dies here, everything stays `quarantined` (excluded from retrieval).
3. **Read structure (chunked):** `UNWIND $ids AS i MATCH (c:Node {id:i})-[:DERIVED_FROM]->(p:Node) RETURN c.id, p.id` and `UNWIND $ids AS i MATCH (m:Memory {id:i})-[:CORROBORATED_BY]->(s:Source) RETURN m.id, s.id, s.status`.
4. **Compute in Python** (Kahn topological order; assert no cycle) -> `{id: (status, taint_parent)}`. Pure function `compute_final(...)` = the unit-testable oracle used by property tests.
5. **Write final statuses (chunks):** `UNWIND $b AS b MATCH (n:Node {id:b[0]}) SET n.status=b[1][0], n.taint_parent=b[1][1]`.
6. **Verify loop:** re-discover; if any member is still `quarantined` (a node created mid-flight) repeat 3-5 (max 5).
7. **Finish:** set `Revocation.state='done'` with counts; return affected actions (`MATCH (a:Action {id:i}) WHERE a.status='tainted'`), **irreversible ones first**, plus `affected_artifacts` (files/commits). On startup `resume_incomplete()` re-runs steps 2-7 for `Revocation {state:'running'}`.
**Dry run** = steps 2(discover only), 3, 4 with **no writes** -> returns the same counts (`would_taint`, `would_preserve`, `would_keep_ok`).
**Reinstate(root):** `R := R \ {root}` (the root is no longer a revoked root), then recompute the
**whole** map from structure with `R` as the root set and `R ∪ {root}` as the discovery seed set:
nodes in `R` keep `revoked` (a revoked root is never reset — a root that is also a descendant of
the reinstated one stays revoked), every node in `desc(R)` is re-derived under the remaining roots,
and nodes outside that descendant union are `ok`. Only the reinstated root's `revoked_at`/`reason`
markers are cleared; `Revocation` rows are history and stay. Idempotent: a root that is not
currently revoked is a no-op. (Corrected 2026-10-17 by P-012: the earlier "reset those descendants
to `ok`; then re-run steps 2–7 for the remaining revoked roots" wording described the blanket-reset
bug — it erased a self-revoked descendant from `R` before the re-resolve, which is the defect fixed
in `7045e39`. See ADR-015.)
**Verified behaviour [V]:** `12_pedigree_core.py` asserts: tainted/preserved/ok mix, idempotent re-revoke, blame chain via `taint_parent`, race (child inserted between discovery and quarantine ends `tainted`), late child born `quarantined`. Cascade cost ~8 us/node [V scale bench]; chunk size 2000 keeps each write ~16 ms.

### 6.4 Blame
Fast path: follow `taint_parent` pointers (`MATCH (n:Node {id:$i}) RETURN n.taint_parent`) to the revoked root. Full path: fetch ancestors by `Q_ANCESTORS` then edges `UNWIND $ids AS i MATCH (c:Node {id:i})-[d:DERIVED_FROM]->(p:Node) RETURN c.id, p.id, d.rel, d.via`; compute BFS parent pointers in Python for the shortest path to each `Source` and to each revoked/untrusted root. (`shortestPath` is allowed only in `WITH/RETURN` with bound endpoints [V]; not needed.) Return `{node, status, roots:[{id, kind, status, path:[ids]}], graph:{nodes,edges}, truncated}`.

### 6.5 Integrity and confidentiality labels
- `low_integrity` (bool, OR over parents) and `conf_eff` (union of tags) are **computed at write time** (6.1); labels are immutable (a "declassify" is a new Memory with an explicit human source). `integrity` of a Source defaults by kind (config): user_prompt/human/file/rules_file = trusted; web/tool_output/mcp_tool_desc = untrusted. Adapters may override.
- Confidentiality check query: `MATCH (m:Node) WHERE m.id IN $ids WITH m WHERE any(t IN coalesce(m.conf_eff, []) WHERE NOT t IN $audience) RETURN m.id, m.conf_eff` [V].

### 6.6 Pre-action gate (deterministic; no LLM)
Input: tool, summary, relied_on ids (explicit) + optional session read-window, `risk`/`effect` (else from the classifier table 7.3), `audience` tags (destination clearance; default `['public']` for network/push/publish tools, `['local']` otherwise).
Decision order (first match wins; every verdict carries `reasons[{code,node_id,path,detail}]`):
1. any relied node or ancestor status in `revoked|tainted|quarantined` -> **block** if risk >= medium else **warn** (allow + reason) [`code: tainted_ancestor`].
2. confidentiality: any tag in union `conf_eff` not in `audience` -> **block** [`code: confidentiality_violation`].
3. `low_integrity` and (`effect='irreversible'` or `risk='high'`) -> **reverify** (human confirmation needed) [`code: untrusted_influence`].
4. any relied id missing in the graph -> **reverify** [`code: not_in_graph`] (we refuse to claim "safe" about unknown lineage). Unanchored actions (no read-window/relied_on at all) -> **allow** with `warning: no_lineage`, because blocking every new session would make the tool unusable [J].
5. else **allow**.
`record=true` stores the Action node with `decision`. Fail-open vs fail-closed is a deployment choice: hooks fail-open by default (a stalled hook does not block in Claude Code unless `onFailure:"block"`), configurable per matcher [D].

### 6.7 What-if and checkpoints with GRAPH.COPY
`whatif(roots[])`: `g.copy('ped:<t>:wi:<hex>')` (atomic, keeps indexes; 20k nodes ~165 ms [V]), run the *real* revoke engine on the copy for each root, diff statuses vs the original, `delete()` the copy in `finally`; cap 2 concurrent what-ifs per tenant; auto-delete copies older than 10 minutes. **Checkpoint/restore (P2):** `copy` to `ped:<t>:ck:<name>`; restore = delete + copy back; demo reset ~170-190 ms [V]. Never use `DUMP/RESTORE` on 4.18.3 (crash) [V].

### 6.8 Load-bearing sources and contamination islands
```cypher
// Q_PAGERANK: DERIVED_FROM points child->parent so rank accumulates on sources/hub memories
CALL algo.pageRank('Node','DERIVED_FROM') YIELD node, score
WHERE 'Source' IN labels(node) AND node.status = 'ok' RETURN node.id, node.kind, score ORDER BY score DESC LIMIT $k   -- [V]
```
Also report exact descendant counts for the top-k by BFS (`Q_DESCENDANTS`) because PageRank is a heuristic ranking, not a count. WCC (`algo.WCC({nodeLabels:['Node'], relationshipTypes:['FEEDS']})`) is optional for a "contamination islands" view [V procedure exists].

## 7. Interfaces
### 7.1 MCP server (name `pedigree`; Streamable HTTP at `/mcp`; also stdio for local)
Tools (tenant comes from the bearer token / env, **never** from a tool argument). OpenCode shows them as `pedigree_<tool>`; Claude Code as `mcp__pedigree__<tool>`. All arguments are validated (pydantic) with the limits in 8.2. All responses are JSON text with `ok` (and, for `revoke`/`blame`/`impact`/`check_action`, `trace`: `[{op,ms,rows}]`); other tools return `ok` only.
| Tool | Input (JSON schema, abbreviated) | Output |
|---|---|---|
| `record_source` | `{kind: enum, uri?: str<=512, title?: str<=160, content_hash?: hex64, integrity?: enum, conf?: str[]<=8}` | `{source_id}` |
| `remember` | `{text: str<=2000, mkind?: enum, derived_from: str[]<=64, corroborated_by?: str[]<=16, conf?: str[]<=8, artifact?: str, content_hash?: hex64}` | `{memory_id, status, low_integrity, conf_eff, warnings[]}` |
| `record_action` | `{tool: str, summary: str<=300, relied_on: str[]<=64, effect?: enum, risk?: enum, artifacts?: str[]<=16, session_id?: str}` | `{action_id, status}` |
| `check_action` | `{tool, summary, relied_on?: str[], effect?, risk?, audience?: str[], session_id?, record?: bool}` | `{decision: allow|warn|reverify|block, reasons[], checked: int}` |
| `revoke` | `{node_id: str, reason: str<=300, dry_run?: bool=true}` | dry: `{would_taint, would_preserve, actions[], irreversible[], artifacts[]}`; real: `{revocation_id, counts, actions[], irreversible[], artifacts[], state}` |
| `reinstate` | `{node_id}` | `{revocation_id, counts}` |
| `blame` | `{node_id, max_depth?: int<=12}` | `{node, status, roots[], graph, truncated}` |
| `impact` | `{node_id, max_depth?}` | read-only descendants grouped by label/status; irreversible actions flagged |
| `audit_sources` | `{limit?: int<=50}` | `[{id, kind, pagerank, descendants, status}]` |
| `whatif` | `{roots: str[]<=5}` | `{diff: {tainted[], preserved[], actions[]}, ms}` |
**Error model.** Tool errors return `isError:true` with JSON `{"error":{"code","message","detail"}}`; REST maps to HTTP: `invalid_argument` 422, `unauthorized` 401, `forbidden` 403, `not_in_graph` 404, `conflict` 409, `too_large` 413, `rate_limited` 429 (+`Retry-After`), `quota_exceeded` 429, `timeout` 504, `internal` 500 (no stack traces to clients; correlation id logged).
### 7.2 REST API (same service layer; FastAPI; OpenAPI at `/docs`)
`POST /v1/events` (capture adapters), `POST /v1/sources|memories|actions`, `POST /v1/gate`, `POST /v1/revoke`, `POST /v1/reinstate`, `GET /v1/blame/{id}`, `GET /v1/impact/{id}`, `GET /v1/audit/sources`, `POST /v1/whatif`, `GET /v1/graph?limit=800&center=id` (UI subgraph), `GET /v1/stats`, `GET /healthz` (process), `GET /readyz` (DB reachable + index operational), `GET /metrics` (admin token), `POST /admin/tenants` (admin token; returns the one-time tenant token), `GET /` (UI).
### 7.3 Event ingestion and risk classification (capture mapping, deterministic)
`POST /v1/events` body: `{runtime, session_id, event: prompt|tool_pre|tool_post|session_start|session_end, tool?, tool_input_summary?, tool_response_digest?, artifacts?: [{path, sha256, op: read|write}], urls?: [..], cwd?, ts}`. Mapping rules (unit-tested with recorded payload fixtures):
| Event/tool | Graph effect |
|---|---|
| `prompt` | `Source{kind:user_prompt, integrity:trusted, content_hash}` + `Session-READ->`; text stored only if `store_text=true` |
| read of local file (Read/Glob/Grep, opencode `read`) | look up `artifact_key = path@sha256` on Memory, then on Action (`MATCH (n:Memory {artifact_key:$k}) RETURN n.id` / same for Action) -> `Session-READ->` that node (**cross-session link**: taint flows through rules files and code edits); else `Source{kind:file|rules_file, uri, content_hash}` |
| web (WebFetch/WebSearch/opencode `webfetch`) | `Source{kind:web, integrity:untrusted, uri, content_hash}` |
| MCP tool output (`mcp__s__t`, `s_t`) | `Source{kind:tool_output, uri:mcp://s/t, integrity:untrusted}`; tool *descriptions* hashed at session start as `mcp_tool_desc` (rug-pull detection: hash change = new Source) |
| write/edit of path matching `memory_globs` (default: `CLAUDE.md`, `AGENTS.md`, `MEMORY.md`, `.claude/**`, `.cursor/rules/**`, `.opencode/**`, `docs/memory/**`) | `Memory{artifact, content_hash(after write), mkind:rule|procedure}` derived from the read window (`via:session_read`) **and** an Action |
| other write/edit | `Action{effect:reversible, artifacts:[path]}` with `RELIED_ON` the read window |
| bash | classify: `git commit` -> Action(reversible, medium, artifacts:[sha]); `git push|npm publish|cargo publish|docker push|kubectl apply|terraform apply|curl/wget with -X POST/-d/-F|ssh|scp|rm -rf|chmod -R|sudo` -> Action(irreversible or unknown, high); other -> low. Heuristic [J], documented, configurable in `policy.yaml` |
Read window: per session, last K=50 distinct READ targets (`via:session_read`) - a **conservative over-approximation**; agent-supplied `cite` ids (via MCP `record_action.relied_on`) tighten it (`via:cite`). Both are measured in E2/E6.

## 8. Capture adapters (verified config formats)
### 8.1 Claude Code (hooks) [D from https://docs.claude.com/en/docs/claude-code/hooks, read 2026-10-15]
- Hook events used: `UserPromptSubmit` (input has `prompt`), `PreToolUse` (input `tool_name`, `tool_input`, `tool_use_id`; can deny), `PostToolUse` (input adds `tool_response`, `duration_ms`). Common fields include `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`.
- Block by printing JSON to stdout with exit 0: `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`.
- **Fail-open caveat:** a timed-out `command`/`http` hook does **not** block the tool call; to block on failure set `"onFailure":"block"` (needs Claude Code >= v2.1.295, per docs).
- Config (`.claude/settings.json`, committed example `adapters/claude/settings.example.json`):
```json
{ "hooks": {
  "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/adapters/claude/pedigree_hook.py\" prompt", "timeout": 10 } ] } ],
  "PreToolUse":  [ { "matcher": "Bash|Write|Edit|MultiEdit|mcp__.*", "hooks": [ { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/adapters/claude/pedigree_hook.py\" pre",  "timeout": 10 } ] } ],
  "PostToolUse": [ { "matcher": "*", "hooks": [ { "type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/adapters/claude/pedigree_hook.py\" post", "timeout": 10 } ] } ]
} }
```
(Matcher semantics for `*` and regex alternation: **[U] confirm with the docs "Matcher patterns" section and a local test**; `${CLAUDE_PROJECT_DIR}` appears in the official example.) `pedigree_hook.py` = stdlib-only (urllib), reads stdin JSON, computes sha256 of files read/written (it runs on the same machine), POSTs to `PEDIGREE_URL/v1/events` with `Authorization: Bearer $PEDIGREE_TOKEN`, and on `pre` returns the deny JSON when `/v1/gate` says `block` (and `reverify` -> `"permissionDecision":"ask"` [D: verify value in docs "PreToolUse decision control"]). Alternative without file hashing: native `{"type":"http","url":...,"headers":{"Authorization":"Bearer $PEDIGREE_TOKEN"},"allowedEnvVars":["PEDIGREE_TOKEN"]}` hooks [D].
### 8.2 OpenCode (plugin) [D from https://opencode.ai/docs/plugins, read 2026-10-15]
- Project plugins in `.opencode/plugins/*.{js,ts}` are auto-loaded; a plugin exports an async function receiving `{project, client, $, directory, worktree}` and returns hooks. Documented hooks include `"tool.execute.before"(input, output)` (`input.tool`, `output.args`; **throwing blocks**, per the official `.env` protection example) and `"tool.execute.after"`; events include `session.created`, `session.idle`, `session.updated`, `file.edited`, `message.updated`. Exact shape of the `after` payload is **[U]**: Phase 0 task = log `input`/`output` of a real session to `docs/consults/opencode-after-shape.json`, then write the mapping against the real shape.
```ts
// .opencode/plugins/pedigree.ts  (sketch; finalise against the logged real payloads)
import type { Plugin } from "@opencode-ai/plugin"
export const Pedigree: Plugin = async ({ directory }) => {
  const url = process.env.PEDIGREE_URL ?? "http://127.0.0.1:8000"; const tok = process.env.PEDIGREE_TOKEN
  const post = (p: string, b: unknown) => fetch(url + p, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${tok}` }, body: JSON.stringify(b), signal: AbortSignal.timeout(3000) })
  return {
    "tool.execute.before": async (input, output) => { const r = await (await post("/v1/gate", { runtime: "opencode", tool: input.tool, args: output.args })).json(); if (r.decision === "block") throw new Error("Pedigree blocked: " + r.reasons?.[0]?.detail) },
    "tool.execute.after":  async (input, output) => { await post("/v1/events", { runtime: "opencode", event: "tool_post", tool: input.tool, /* map output */ }) },
  }
}
```
MCP registration for OpenCode (`opencode.json`; `type`, `command` array, `environment`, `enabled`, `timeout` ms default 5000; remote: `type:"remote"`, `url`, `headers`, `oauth:false`) [D: https://opencode.ai/docs/mcp-servers]:
```json
{ "$schema": "https://opencode.ai/config.json",
  "mcp": { "pedigree": { "type": "remote", "url": "http://127.0.0.1:8000/mcp", "oauth": false,
           "headers": { "Authorization": "Bearer {env:PEDIGREE_TOKEN}" }, "enabled": true, "timeout": 10000 } } }
```
### 8.3 Cursor / others
Via MCP only (agent-reported edges, `via:agent_reported`, lower weight, labelled in the UI). Cursor hooks are out of scope for the hackathon.

## 9. Security model
- **Tenant isolation, 3 layers:** (1) tenant id validated by regex and derived **only** from the bearer token lookup in the registry (never from request bodies/args); (2) graph name built by one function `graph_name(tenant)`; no tenant-controlled string reaches Cypher text (labels/types are constants); (3) defence in depth: a FalkorDB ACL user per tenant (`~ped:<t> ~ped:<t>:wi:* ~ped:<t>:ck:*`, `-@all` + the minimal command list; `+info` is required by the python client [V]); the API opens the tenant connection with that user. Verified: cross-tenant read/write/copy denied [V examples/py/13]. Residual: `GRAPH.LIST` exposes all graph names to any user holding `+graph.list` [V] - omit it for tenant users. ACL availability on FalkorDB Cloud Free: **[U]**.
- **AuthN:** bearer tokens `ped_<tenant>_<32 random bytes b64url>`; only `sha256(token)` stored in the registry graph; `hmac.compare_digest`; admin token from env for `/admin/*` and `/metrics`; tokens shown once; rotation = new token + revoke old. MCP endpoint validates the same bearer (verified spike `tech/examples/mcp/mount_in_fastapi.py`: ASGI bearer middleware around `streamable_http_app()`; per-request tenant must be passed via a contextvar set in the middleware; SDK `TokenVerifier`/`AuthSettings` exist in `mcp` 2.3.0 but are **[U]** - not needed).
- **Input limits:** body <= 256 KB; per-field limits in 7.1; arrays capped; ids `^[A-Za-z0-9._:/@#-]{1,128}$`; per-tenant node cap (default 200k; 20k on Cloud Free) -> `quota_exceeded`; rate limit 120 req/min/token (in-memory bucket) + stricter 10/min for `revoke`/`whatif`.
- **Query safety:** parameterised static queries only; read queries via `ro_query`; per-query timeout (reads 5 s, writes 15 s; server `TIMEOUT_MAX 60000`); `QUERY_MEM_CAPACITY 1 GiB` and `TIMEOUT_MAX` are **mandatory** server config [V, GOTCHAS #1]; var-length traversals only with BFS or depth <= 3; chunked writes (<= 2000 ids).
- **Secrets:** `.env` git-ignored; `.env.example` committed; tokens never logged (log only the tenant id and a token fingerprint = first 8 hex of sha256); repo secret scan in CI (`gitleaks`-style regex test in `tests/test_no_secrets.py`).
- **Data hygiene:** hash-only mode default for prompts/file contents (store hash + short title); demo uses synthetic or own data only (rules #6).
- **Capture integrity:** lineage is written by hooks/plugins, not by the model. MCP `remember`/`record_action` edges are tagged `via:agent_reported` and shown differently; an injected agent can lie through MCP, so the gate also uses hook-captured read windows.
- **Not covered / residual:** a compromised host can forge hook payloads; plaintext link app<->DB on Cloud Free (no TLS, [D docs.falkordb.com/cloud/tiers/free]); heuristic bash classifier; no encryption at rest.

## 10. Failure modes and responses
| Failure | Behaviour |
|---|---|
| FalkorDB down/slow | `/readyz` 503; API returns 503 `internal` with retry hint; **hooks fail open** (agent keeps working; events are spooled to `~/.pedigree/spool.jsonl` and replayed - P2) except configured fail-closed matchers |
| Hook times out / server cold (Render sleeps 15 min, ~1 min wake) | fail-open by default; demo pre-warms; spool |
| Revoke crashes mid-way | nodes remain `quarantined` (safe); `Revocation.state='running'`; startup `resume_incomplete()` finishes (idempotent) |
| Race: ingest during revoke | child born `quarantined` if any parent quarantined/tainted/revoked; fixpoint + verify loop; tested with an injected hook |
| Cascade > 50k nodes | chunked writes; async mode: `202 {revocation_id}` + poll; readers may see stalls (measured p95 5->452 ms during a 0.5 s write [V]) |
| Unknown ids | `not_in_graph` (never "no impact") |
| Duplicate ids / retries | unique constraint -> `conflict`; ingest is idempotent by client-provided or content-derived ids |
| Poisoned lineage (agent lies via MCP) | edges flagged `agent_reported`; hook-derived read window still applies; documented limitation |
| Over-approximation (session window) | reported ratio; `cite` tightens; `preserved` only when explicit independent support exists |
| Cloud Free stopped after 1 day idle / deleted after 7, no persistence | seed demo tenant on boot; local setup is the mandatory fallback |
| Disk/RAM limits | node caps per tenant; E4 benchmark capped at 1e6 nodes |
