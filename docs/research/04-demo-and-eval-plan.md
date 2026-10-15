# 04 - Demo and evaluation plan for Pedigree

Principles: deterministic core (no LLM in the graph logic), LLM only for the demo agent, everything runs offline with local Docker FalkorDB, **no credit card anywhere**, every number in the README is reproducible by `make eval`.

## 1. Graph model (per-tenant graph `ped_<tenant>`; one FalkorDB graph per tenant)
- Nodes: `Source{id,kind,uri,hash,trust,status}` (kind: web|file|tool_output|user|rules_file|mcp_tool_desc), `Memory{id,text,kind,conf[],status,version}`, `Action{id,tool,args_hash,effect,status}` (effect: reversible|irreversible), `Session{id,runtime}`, `Agent{id}`.
- Edges: `(Memory)-[:DERIVED_FROM{kind}]->(Source|Memory)`, `(Memory)-[:CORROBORATED_BY]->(Source)` (independent support), `(Action)-[:RELIED_ON{via:'cite'|'session_read'}]->(Memory|Source)`, `(Agent)-[:WROTE]->(Memory)`, `(Session)-[:READ]->(Memory|Source)`, `(Memory)-[:SUPERSEDES]->(Memory)`.
- Status values: `ok | suspect | revoked | quarantined | preserved` (preserved = would be tainted but has independent support).
- Core queries (to list in README; **verify each runs on the pinned FalkorDB version**; EXISTS-subquery support is **[UNVERIFIED]**, otherwise compute support in two steps in Python):
  1. closure: `MATCH (s:Source {id:$id})<-[:DERIVED_FROM*1..10]-(m:Memory) RETURN DISTINCT m.id`
  2. independent support: `MATCH (m:Memory)-[:CORROBORATED_BY]->(c:Source) WHERE m.id IN $T AND c.status='ok' AND NOT c.id IN $tainted_sources RETURN m.id`
  3. affected actions: `MATCH (a:Action)-[:RELIED_ON]->(x) WHERE x.id IN $T RETURN a`
  4. blame path: `algo.SPpaths` / `MATCH p=shortestPath((a:Action {id:$id})-[:RELIED_ON|DERIVED_FROM*1..10]->(s:Source))`
  5. load-bearing sources: `CALL algo.pageRank` on reversed derivation edges, or descendant counts
  6. what-if: `GRAPH.COPY` -> revoke on copy -> diff -> `GRAPH.DELETE` copy
- Revocation = **barrier first**: set `quarantined` (excluded from retrieval) before computing repair; never hard-delete (history preserved).

## 2. Capture (the differentiator)
- **Claude Code**: `PreToolUse`/`PostToolUse` hooks receive JSON on stdin (incl. `tool_name`, `tool_input`, `tool_response`, `session_id`, `transcript_path`) -> POST to Pedigree. `PreToolUse` can deny. **[V]** Hooks docs (https://docs.claude.com/en/docs/claude-code/hooks) mention `session_id`, `transcript_path`, `tool_use_id`, `tool_response`, and a `PreToolUse` JSON output `hookSpecificOutput.permissionDecision: "deny"` with `permissionDecisionReason` to block. Exact field set per event: still test locally.
- **OpenCode**: **[V]** plugin returning `"tool.execute.before"` / `"tool.execute.after"` handlers (`input.tool`, `output.args`; throwing in `before` blocks, per docs example that rejects reading `.env`) - https://opencode.ai/docs/plugins. Docs also list session events (`session.idle`, `session.updated`). Test against your installed OpenCode version.
- **MCP proxy fallback**: Pedigree MCP server also exposes `record_source/record_action/check_action` so any MCP client (Cursor) can call it; weaker because the agent could skip or lie, so label such edges `via:'agent_reported'` and weight lower. Hooks/plugins run out-of-band = unforgeable by the model (argument from https://arxiv.org/html/2606.24322v1).
- Influence rule (conservative): every Source/Memory read earlier in the same session is a candidate `RELIED_ON` for later Actions (`via:'session_read'`); optional `cite` tightens it. Report the over-approximation ratio.
- Free local trace data: record 5-10 of your own sessions on a throwaway repo (rule 6: "your own" data allowed; no private code/data).

## 3. Interfaces
- **MCP server** (Streamable HTTP `/mcp`; Python MCP SDK with bearer `TokenVerifier`; verify current SDK API): `record_source, remember, record_action, check_action, revoke_source(dry_run), blame, affected, explain, audit_sources`. Fixed tool catalogue, parameterised Cypher only; arguments validated against the graph; unknown id -> "not in the graph" (the organizer-recommended honesty move).
- **Auth/tenancy**: token -> tenant -> graph name; FalkorDB ACL users per tenant with `%RW~ped_<tenant>` key patterns (**verify the exact ACL syntax and that GRAPH.QUERY honours it on your version**; `ACL SAVE`).
- **Observability**: structured JSON log per request (tenant, tool, ms, rows, graph), `/metrics` counters, and an in-UI "trace" strip (tool/args/ms/rows - mirrors the organizer's blog pattern).
- **UI**: single page (Cytoscape.js or similar): graph, red taint propagation animation, "Revoke source" button, revert list (files/commits/irreversible effects), depth slider (1 vs 6).

## 4. Evaluation (honest, runnable, free)
Common: seeded RNG, N runs, report mean ± 95% CI (Wilson for proportions), publish the generator and raw CSV. State clearly what each experiment does and does not show.

### E1 - Correctness of cascade on synthetic DAGs (implementation + baseline semantics)
- Generator: S sources (10-1,000), M memories (100-100k), depth 1-8, fan-in 1-4, corroboration prob p_c ∈ {0, .1, .3}, A actions. Ground truth by construction (set of truly tainted vs truly independently supported).
- Systems: **B0** vector-memory-style (delete items most similar to the poisoned text; use a cheap local embedding or TF-IDF so no API), **B1** Graphiti-`remove_episode` semantics (delete only items whose *first* provenance is the source; shared items remain), **B2** flat 1-hop provenance, **B3** temporal-only invalidation (supersession edges only), **B4** full cascade *without* support check (PACMI/MemoRepair-style "withdraw all descendants"), **P** Pedigree cascade + independent support.
- Metrics: recall of tainted items (residual contamination), over-invalidation (healthy items removed), precision, affected-action recall.
- Honesty note: ground truth is built in, so this measures the **cost of baseline semantics**, not discovery; do not present as an end-to-end result.
### E2 - Provenance-capture fidelity (the non-tautological one)
- Take recorded real traces (or the synthetic graphs) and randomly drop/corrupt edge capture at rates {0,1,2,5,10}%. Compare **precise capture** vs **conservative session-level capture**: leakage (missed tainted items) vs over-approximation (extra items flagged). This empirically replicates/extends MemoRepair's "1% drop -> 17.7% leak" finding (https://arxiv.org/pdf/2605.07242v1/__stdout.txt) and shows the trade-off we chose. Expect: conservative capture leaks ~0 at the price of higher over-flagging; report the actual numbers.
### E3 - Attack zoo (agent-level, scripted + 1 LLM agent)
Seven scenarios, each mapped to a published class (our replay is a **simulation of the attack pattern**, not a reproduction of the papers' numbers):
1. Poisoned web page -> memory -> later commit (Rehberger delayed invocation pattern, https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/)
2. Query-only memory injection by another user into shared memory (MINJA class, https://arxiv.org/abs/2503.03704)
3. Backdoored rules file with hidden Unicode (https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents)
4. MCP tool description rug pull (https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks)
5. Sleeper memory: benign-looking memory written Monday, triggers Friday
6. Confidentiality: summary memory derived from tenant-A/HR data requested by a public-facing task (confused deputy)
7. Stale decision: superseded source still driving a recommendation
- Metrics: unsafe-action rate with/without Pedigree gate, benign-task success (utility), detection-to-containment steps/time, irreversible-effect recall, revert-list precision. Scripted deterministic agent (n=100 seeded variations) + a real LLM agent on 3 scenarios, n as quota allows (report n).
### E4 - Performance on FalkorDB
- Graph sizes 1e3, 1e4, 1e5, 1e6 nodes (stop where local disk/RAM allows; measure RSS); depth 2-8; fan-out 2-10. Report p50/p95/p99 for closure, blame, what-if copy; ingest throughput. Concurrency: K ∈ {1,4,16,32} clients, writes to **different tenant graphs** vs **same graph** (documented serialisation per graph - measure rather than assume). Use `GRAPH.RO_QUERY` for reads.
### E5 - Tenant isolation and concurrency conformance (Graphiti #1331/#1676 class)
- Property-based test: T tenants × concurrent writers; afterwards assert every node's `tenant` property equals its graph and no cross-graph edge/name leakage; separate ACL test: tenant-A credential gets a permission error on tenant-B graph (**verify**). Plus a race test for `revoke` while writers add derived memories (barrier semantics: no new memory derived from a quarantined source becomes `ok`).
### E6 - Real-trace case study (small, honest)
- n ≈ 5-10 own sessions: counts of sources/actions/edges; over-approximation ratio; fraction of later actions flagged after injecting a known-bad source; manual check of 20 flagged actions to estimate precision (report that it's a hand-labelled small sample).

## 5. 3-minute demo script (video; also live if deployed)
| Time | Show | Say |
|---|---|---|
| 0:00-0:20 | A coding agent (OpenCode/Claude Code) fixing a bug on a sample repo; Pedigree sidebar silently logging | "Agents remember and act. When one source turns out to be bad, nobody can say what it already affected. Pedigree is git blame and git revert for what an agent believes." |
| 0:20-0:50 | Agent reads a web page/rules file (planted), writes memories, edits a file, commits | "Everything is captured out-of-band by hooks into FalkorDB - one graph per tenant." Show graph growing |
| 0:50-1:30 | Security alert: source flagged. Click **Revoke**. Depth slider 1 -> 6; red wave spreads; 2 items at depth 1, 31 at depth 6 incl. a commit and an outbound call | "A join sees two; a graph sees the commit six hops away." Show blame path for the commit |
| 1:30-2:00 | Same source: two memories turn **green "preserved"** because independent support exists | "Naive cascades delete these. We keep them and show why." Show over-invalidation bar chart |
| 2:00-2:25 | Agent tries `git push` relying on a quarantined memory -> gate blocks with path; ask "does anything depend on X?" for an id not modelled -> "not in the graph" | "The gate answers with the path. Unknown is unknown." |
| 2:25-2:50 | Eval table (E1/E2/E3) + isolation test green + latency | "Measured on a reproducible benchmark; tenant isolation tested against the failure class found in Graphiti issues." |
| 2:50-3:00 | Repo, tracks, tools used | "Track 2 and Track 1. All graph logic is Cypher over FalkorDB; remove it and nothing works." |
Rehearse 3x; record in 2 segments; captions on. Backup: a pre-recorded GIF per scene.

## 6. Free, no-card stack (limits **[U]** unless stated; re-check in your accounts)
- **FalkorDB**: local Docker (free) https://hub.docker.com/r/falkordb/falkordb ; Cloud Free: 100 MB, no card, **no TLS** (verified https://docs.falkordb.com/cloud/tiers/free).
- **LLMs for the demo agent only**: Groq - gpt-oss-120b/20b, Qwen: 30 RPM, 1K RPD, 8K TPM, 200K TPD per model (verified on https://console.groq.com/docs/rate-limits; page says limits are per-account, check yours; 8K TPM is tight, so keep prompts small); Google AI Studio Gemini free tier - limits are per model/project and shown in AI Studio (https://ai.google.dev/gemini-api/docs/rate-limits), no card; OpenRouter free models - 20 RPM, 50 RPD without purchased credit (https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know); Mistral free mode **[U]**. Cerebras needs a payment method - avoid. Overview: https://klymentiev.com/blog/free-llm-api (third-party). Wire a provider fallback chain; cache LLM outputs in the repo for reproducible demos.
- **Hosting**: Render free web service, no card, spins down after 15 min idle (verified https://render.com/docs/free); run the API there and point at Cloud Free (plaintext - synthetic data only) or skip hosting FalkorDB and ship Docker Compose + video.
- **Disk-light**: FalkorDB image is small; cap E4 at 1e6 nodes; store eval CSVs, not dumps.

## 7. Judge talking points
- "The graph is the product: remove FalkorDB and revoke/blame/gate don't exist." (rule 3)
- Depth-1 vs depth-6 on screen; path shown for every decision (organizer's own advice).
- Fixed, parameterised Cypher via MCP - the LLM never writes Cypher; "not in the graph" is a first-class answer.
- Honest positioning vs PACMI/MemoRepair/MAP-Graph and other entries: algorithm known; contribution is real capture, independent-support preservation, joint integrity/confidentiality labels, and measurement.
- Tenant isolation tested against a real failure class in Graphiti (#1331/#1676), not just claimed.
- Be ready to explain every query and model choice (rule 12); disclose AI assistance (rule 11).

## 8. Limitations (state them in README and video notes)
- Does not prevent prompt injection; it **contains, explains and reverts** after detection/suspicion.
- Detection of "bad source" is an input (human/scanner/alert), not solved here.
- Session-level capture over-approximates; precision depends on `cite` quality.
- Cannot undo external effects (emails, pushes already pulled); it **lists** them.
- LLM-mediated paraphrase can launder content so a derived memory lacks an edge if the agent writes memory through a path we don't hook; coverage = what the hooks see.
- Free-tier LLM quotas and Cloud Free (100 MB, no TLS) limit scale and security of the hosted demo; benchmarks run locally.
- Eval E1 has built-in ground truth; E3 is simulation of attack patterns; E6 is small-n.
