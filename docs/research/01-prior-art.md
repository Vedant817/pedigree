# 01 - Prior art: what exists, what it does NOT do

Labels: **[V]** verified in a source I opened/searched on 2026-10-15; **[U]** unverified/secondary. All claims cite a URL.

## A. Production / open-source agent-memory systems

### 1. Graphiti / Zep (temporal knowledge graph; FalkorDB is a supported backend)
- **Does:** Builds a temporally-aware KG from "episodes"; edges carry `valid_at`/`invalid_at`; a newer contradictory edge invalidates an older one when its `valid_at` is later; multi-tenancy via `group_id`; MCP server (`add_memory`, `search_nodes`, `search_memory_facts`, episode ops). Zep paper: https://arxiv.org/abs/2501.13956. Repo: https://github.com/getzep/graphiti. MCP README: https://github.com/getzep/graphiti/blob/main/mcp_server/README.md **[V]**
- **Invalidation semantics:** `remove_episode(uuid)` deletes the episode, the entity edges whose *first* provenance entry is that episode, and entity nodes mentioned only by that episode; edges shared with other episodes stay (https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py, https://github.com/getzep/graphiti/pull/261). A later MCP commit makes `delete_episode` cascade to extracted edges/orphan entities (https://github.com/getzep/graphiti/commit/9960ff2a12d46eff4329ae2f634f22e244640018). **[V via search synthesis; re-read the code before quoting in the README]**
- **Does NOT:** track *downstream derived beliefs or actions* (a summary memory, a decision, a commit) that depended on an episode; no trust/taint state; no "what did the agent do because of this?"; temporal invalidation answers "which fact is newer", not "which fact came from a bad source".
- **FalkorDB-specific bugs relevant to multi-tenant memory:** `add_episode()` mutates a shared `self.driver`, causing cross-group contamination - issue #1331 (open, created 2026-03-19; https://github.com/getzep/graphiti/issues/1331) and #1676 "Concurrent multi-group_id episode processing silently corrupts data across FalkorDB graphs" (created 2026-07-23, closed 2026-09-08; https://github.com/getzep/graphiti/issues/1676). **[V via GitHub API]** Good evidence that tenant isolation under concurrency is a real, silent failure class.

### 2. Cognee
- **Does:** ECL pipeline to build graph+vector memory; FalkorDB adapter (community-maintained: https://docs.cognee.ai/setup-configuration/community-maintained/falkordb; FalkorDB docs page https://docs.falkordb.com/agentic-memory/cognee); `forget` deletes graph, vector and relational data for a dataset/item (`memory_only=True` keeps raw files): https://docs.cognee.ai/core-concepts/main-operations/forget **[V]**
- **Does NOT:** cascade through *derived beliefs/actions* with independent-support preservation; no action gating; deletion is dataset/item-scoped, not lineage-scoped. **[inferred from docs]**

### 3. Mem0
- **Does:** LLM-extracted fact memory. Mem0 v3 OSS is described as add-only with explicit update/delete; graph memory removed from OSS and kept in the managed platform (secondary source: https://www.cognee.ai/ai-memory-tools-vs-databases, https://mnemoverse.com/docs/library/agent-memory-deduplication). Paper: https://arxiv.org/abs/2504.19413. Repo https://github.com/mem0ai/mem0 **[U - vendor-comparison pages are biased; verify on mem0 docs]**
- **Does NOT:** record where a fact came from beyond metadata; no dependency cascade; no quarantine; no gate. **[U]**

### 4. FalkorDB GraphRAG-SDK
- **Does:** Builds a KG from documents and answers questions over FalkorDB (https://github.com/FalkorDB/GraphRAG-SDK) **[V repo exists; details not re-read]**.
- **Does NOT:** model agent runtime events (tool calls, sessions, actions) or invalidation. It is a document-QA toolkit, i.e. closer to the "Company Brain" shape.

### 5. FalkorDB's own memory/MCP offerings
- **FalkorDB-MCPServer:** generic `query_graph(query, params, readOnly)` over any graph (https://github.com/FalkorDB/FalkorDB-MCPServer/) - the LLM writes Cypher. **Agentic Memory docs** route to Graphiti and Cognee (https://docs.falkordb.com/agentic-memory, https://docs.falkordb.com/agentic-memory/cognee). **[V via search]**
- **Does NOT:** ship a provenance/revocation layer, a safe fixed tool catalogue, or an evaluation harness. Note the organizer's blog explicitly recommends a **fixed catalogue of human-written parameterised Cypher via MCP** over LLM-written Cypher (https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph) - we align with this.

### 6. Neo4j Agent Memory (neo4j-labs)
- **Does:** short-term messages + long-term entities + **reasoning traces** (application-recorded steps and tool calls); `:TOUCHED` edges link steps to entities for "audit reasoning" and `getEntityProvenance`. https://neo4j.com/labs/agent-memory/ , https://neo4j.com/labs/agent-memory/how-to/audit-reasoning/ , repo https://github.com/neo4j-labs/agent-memory **[V]**
- **Does NOT:** revoke/quarantine from a bad source, compute independent support, or gate actions (audit is read-only). Proves that "trace -> entity provenance" is table stakes, not novel. Not FalkorDB.

### 7. LangGraph
- **Does:** checkpointers (thread state, "time travel" to a previous checkpoint) + Store for cross-thread long-term memory (https://langchain-ai.github.io/langgraph/ **[U - not re-read]**).
- **Does NOT:** semantic revocation; rewinding a checkpoint rewinds *everything after it*, not "only what depended on source X". Our system is complementary (selective vs total rewind).

### 8. MemGPT / Letta
- **Does:** OS-style paging of memory blocks; current Letta memory = git-backed **Context Repositories** where agents edit Markdown files and git records every change (https://www.letta.com/blog/context-repositories/) **[V]**.
- **Does NOT:** record *why* a memory exists (which source/session) as a queryable graph, or compute blast radius. Git history is file-level and linear. Closest to "git for memory" idea - so our "git blame/revert for beliefs" pitch must emphasise **graph-level, cross-source, selective** revert.

### 9. A-MEM (Zettelkasten-style agentic memory)
- **Does:** notes with generated keywords/tags and links; "memory evolution" rewrites older notes when new ones arrive (https://arxiv.org/abs/2502.12110) **[V repo/paper exists]**.
- **Does NOT:** keep immutable provenance; evolution *mutates* memory, making retroactive repair harder. Illustrates why append-only provenance + validity state matters.

## B. Research on exactly our topic (academic prior art - do not claim novelty over these)
| Work | What it provides | Gap it admits / leaves |
|---|---|---|
| **PACMI** (arXiv 2610.05732, https://arxiv.org/html/2610.05732v1) | Typed dependency graph of memories+evidence, validity states, cascading invalidation, preserves history; frames as natural-language TMS (JTMS/ATMS/AGM, PROV-DM) | Edges supplied by annotation; inducing edges from raw text unsolved (per my earlier reading of the paper) **[V by earlier read; re-confirm wording before quoting]** |
| **MemoRepair** (arXiv 2605.07242, https://arxiv.org/abs/2605.07242) | Barrier-first withdrawal then rebuild of only validated successors; exact min-cut selector | Zero-leak guarantee needs *complete* provenance: dropping 1% of edges -> 17.7% leak, 5% -> 61.8% (https://arxiv.org/pdf/2605.07242v1/__stdout.txt). Targets stale-memory repair, not adversarial poisoning |
| **MAP-Graph** (arXiv 2608.10509, https://arxiv.org/abs/2608.10509) | Typed execution graph (agents, sources, memories, claims, actions), permission filtering, multiplicative ancestry trust, action gate with Allow/Block/Reverify/Redact/AskUser, lineage for audit | Research prototype; no live runtime capture adapters (my reading; **[U]**) |
| **Governed Shared Memory for Multi-Agent LLM Systems** (https://arxiv.org/html/2606.24535) | Governance layer for shared memory **[V title only]** | - |
| **Non-malleable, origin-bound authority** (https://arxiv.org/html/2606.24322v1) | Argues poisoning defence needs origin-bound authority rather than mutable lineage | Important caveat: lineage metadata itself can be forged if the agent writes it; so capture must be done *outside* the agent (hooks/proxy) - a design requirement for us |
| **OWASP Agent Memory Guard** (https://owasp.org/projects/agent-memory-guard) | Policy screening of memory operations | No lineage / no cascade |
| **CaMeL** (https://arxiv.org/abs/2503.18813) and **FIDES** (https://arxiv.org/abs/2505.23643) | Capability / information-flow-control labels (confidentiality + integrity) propagated through a single agent run; block policy-violating tool calls | Per-run, in-process; do not persist the flow graph across sessions/agents as shared, queryable infrastructure |

## C. In-event prior art (public GitHub entries created since the event start; see 06-competitor-census.md)
- **kintsugi** (Itz-Agasta): "Repair poisoned shared memory in a multi-agent system... walks a provenance graph in FalkorDB... re-runs only those actions against clean memory, stops early where a re-run gives the same result, and lists external effects that cannot be undone. Work in progress." (README was 378 bytes at snapshot) - **the closest conceptual overlap to our core**.
- **undograph** (Tejas-Sands): FalkorDB provenance graph, "undo" cascade, design doc; no MCP; no real-session capture (README keyword scan).
- **lineage** (Vaibhaav-Tiwari): company-brain "unlearn" with MCP, `GRAPH.COPY`, ACL and an eval folder - the most feature-complete overlap.
- **honest-memory** (retailbox-automation): write-time checks for memory.
- Others: ripple, shaky-ground (retraction cascade), accesscut (access revocation), agentmesh (contradictions in shared memory), crew-memory-graph (shared memory + tenants + benchmark).
- Common pattern **[INFERRED from READMEs]:** all use *synthetic/hand-authored* provenance edges; none that I found captures provenance from a real coding-agent session (OpenCode / Claude Code / Cursor); none combine integrity and confidentiality labels; none benchmark over-invalidation vs under-invalidation against Graphiti-style semantics.

## D. Honest novelty statement
1. **Not novel:** typed derivation graph + cascading invalidation (PACMI, MemoRepair, MAP-Graph; three+ entries here). Pre-action gate with Allow/Block/Reverify (MAP-Graph). Audit queries (Neo4j Agent Memory).
2. **Plausibly novel / differentiating (as a *shipped system*, not as an algorithm):**
   - Provenance captured **automatically and out-of-band** from real agent runtimes (Claude Code hooks, OpenCode plugin, MCP proxy), addressing the papers' own admitted weak point (complete influence edges) and the forgeable-lineage objection.
   - **Independent-support preservation** (`DERIVED_FROM` vs `CORROBORATED_BY`) with *measured* over-/under-invalidation vs baselines.
   - **Integrity + confidentiality** labels on one graph (IFC for persistent memory) - CaMeL/FIDES do this per-run only.
   - A **tenant-isolation + concurrency conformance suite** for FalkorDB-backed agent memory motivated by Graphiti #1331/#1676.
   - A **reproducible attack zoo** mapped to published incidents (Rehberger Gemini memory, SpAIware, Rules File Backdoor, MCP tool poisoning, MINJA) with unsafe-action-rate and utility numbers.
3. Everything in (2) is *engineering + evaluation* novelty. Say so in the README; judges and FalkorDB staff will recognise the papers.
