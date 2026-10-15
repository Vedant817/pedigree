# 02 - Real, under-addressed problems (and which one to build)

Scoring scale: 1 (low) - 5 (high). Odds are **qualitative judgement**, not statistics. Sources are in 05-sources.md.

## 0. What ~90% of entrants will build (and why it loses)
Evidence: 61+ public repos in the first ~18 hours (06-competitor-census.md).
| Archetype | Share (approx., census) | Why it blends in |
|---|---|---|
| Blast-radius / root-cause / "what breaks if X changes" over a synthetic dependency graph | ~13 / 61 | Copy of the organizer's own launch demo (https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph). The blog gives full code and four example questions; entrants reuse them. Judges will have seen it a dozen times. |
| "Company Brain" over docs/tickets/people | ~6-7 | Track 3 default; demo is a chatbot with citations. |
| Fraud-ring / security-threat triage on synthetic data | ~7-8 | The two examples listed in Track 1's description. |
| Generic agent memory on FalkorDB (episodic/semantic nodes, recall) | ~10 | "Chatbot with a graph" - fails the "graph is doing work it couldn't without" test unless depth-4 is shown. |
| Memory repair/poisoning/provenance (our candidate) | ~6-8 direct | Already a visible cluster; most use hand-authored synthetic provenance. |
| Health / domain verticals | ~3-5 | Data-sourcing risk (rule 6) and credibility risk. |
Common weaknesses (README scans): synthetic data only, no measured evaluation, no real agent integration, one-tenant toy graph, LLM writing Cypher or answers without checking, no tests. Beating these on *measurement, real integration and honesty* is cheaper than beating them on idea.

## 1. Candidate (a): Provenance, taint and revocation for agent memory/actions
**Problem is real and growing.** Evidence:
- OWASP lists *Memory & Context Poisoning* as ASI06 of the Agentic Top 10 (https://genai.owasp.org/download/52117/).
- Attacks are persistent and cross-session: Rehberger's Gemini delayed-tool-invocation memory poisoning (https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/), ChatGPT SpAIware (https://embracethered.com/blog/posts/2024/chatgpt-macos-app-persistent-data-exfiltration/), MINJA query-only injection, reported 98.2% injection / 76.8% attack success in the paper's setup (https://arxiv.org/abs/2503.03704), AgentPoison (https://arxiv.org/html/2407.12784).
- Coding-agent supply chain: Rules File Backdoor via invisible Unicode in Cursor/Copilot rules (https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents); MCP tool poisoning and rug pulls (https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks).
- Defenders mostly *detect at write time* (OWASP Agent Memory Guard https://owasp.org/projects/agent-memory-guard; scanners like MCP-Scan https://invariantlabs.ai/blog/introducing-mcp-scan). Detection fails eventually; then the question is **"what did we already believe/do because of it?"** - that is a lineage question.
- **Who suffers:** teams running coding agents (Claude Code / Cursor / OpenCode) with persistent memory, rules files and MCP servers; multi-agent platforms with shared memory.
- **Why a graph:** "everything derived (transitively) from source S, minus what has independent support, plus actions that relied on it" is variable-length reachability + set difference; relational joins need recursive CTEs and break at depth. Depth is genuinely unbounded (summary of summary of fetched doc). Also centrality/WCC for "which unrevoked sources are load-bearing" and `GRAPH.COPY` for what-if.
- **Prior-art overlap:** HIGH (section 01 B and C). PACMI, MemoRepair, MAP-Graph; kintsugi, undograph, lineage in-event.
- **Gap that remains (this is the real contribution):**
  1. *Capturing* provenance from real runtimes. MemoRepair shows 1% dropped edges -> 17.7% leak (https://arxiv.org/pdf/2605.07242v1/__stdout.txt); all in-event entries I scanned hand-author edges.
  2. Lineage must be recorded **outside the agent's control** (hooks/proxy), otherwise an injected agent can forge it (argument in https://arxiv.org/html/2606.24322v1).
  3. **Over-invalidation** cost: naive full cascade nukes things with independent support. Measuring this trade-off honestly is rare.
  4. Reaching **actions** (commits, file edits, shell commands, outbound calls) and flagging *irreversible* ones.
- Feasibility (solo, ~3 days): **4/5** if capture is conservative (session-level reads->actions) and the engine is simple. Demo-ability **5/5** (live injection -> "Revoke" -> graph lights up -> revert list). Track fit: Track 2 strong (memory + shared state + tenants), Track 1 good (agent uses graph algorithms as tools to triage and act).
- **Odds:** crowded; competing on the idea is a coin-flip among 6-8 near-identical entries. Odds rise only if capture/eval/hardening are visibly better. Candid: *moderate-low* for a track prize, *decent* for resume value either way.

## 2. Candidate (b): Decision rot / stale assumptions
- **Evidence:** staleness and conflicting-memory failures are documented in agent-memory benchmarks and PACMI's motivation (https://arxiv.org/html/2610.05732v1). In-org version: "why did we choose X and is the assumption still true?"
- **Overlap:** HIGH - ripple, decisiongraph-ai, lineage, shaky-ground in this event; Graphiti temporal invalidation in production.
- **Feasibility 4/5; demo 3/5** (less visceral than an attack); Track 3 fit.
- **Verdict:** real but crowded and weak demo. **Fold into (a) as a feature** (`SUPERSEDES` edge + "assumption withdrawn" is the same cascade as "source revoked").

## 3. Candidate (c): Multi-agent consistency / shared-memory races
- **Evidence:** MAST taxonomy shows inter-agent misalignment is a leading failure category (https://arxiv.org/abs/2503.13657). Concretely for FalkorDB: Graphiti issues #1331 and #1676 (silent cross-tenant data corruption under concurrent writes) (https://github.com/getzep/graphiti/issues/1331, https://github.com/getzep/graphiti/issues/1676).
- **Overlap:** MEDIUM - agentmesh, crew-memory-graph, agent-office-relay do coordination/handoff; none found with a formal isolation/concurrency conformance suite **[U - scan only]**.
- **Feasibility:** 3/5 as a flagship (hard to demo visually; "no bug happened" is not a demo). 5/5 as a **component**.
- **FalkorDB facts to use (verify before claiming):** one instance holds many graphs; reads parallel, writes serialized per graph, different graphs written concurrently; per-graph ACL patterns `%R~key`/`%RW~key`; `GRAPH.COPY` atomic snapshot (FalkorDB docs; **[U - secondary/search-derived; test locally and quote only what you measured]**).
- **Verdict:** ship as the **tenant-isolation + concurrency test suite** inside the flagship - cheap, directly Track-2-relevant ("separate memory per user/tenant", "high-concurrency reads and writes" are named in the track description), and adds the production-grade feel.

## 4. Candidate (d): Stronger - Information-flow control (IFC) for persistent agent memory = integrity AND confidentiality on one graph
- **Insight:** poisoning (untrusted data flowing *into* trusted decisions) and leakage (confidential data flowing *out* through derived summaries) are the same graph problem: labels propagate along derivation edges; policy is checked at read/act time. Academic IFC for agents exists per run (CaMeL https://arxiv.org/abs/2503.18813; FIDES https://arxiv.org/abs/2505.23643, which labels every value with confidentiality and integrity); persistent cross-session/agent flow graph as *infrastructure* is what MAP-Graph/PACMI gesture at but do not ship with capture.
- **Evidence for the confidentiality half:** summaries/derived memories laundering permissions is the standard "confused deputy" scenario in shared multi-agent memory; MAP-Graph filters by permission eligibility (https://arxiv.org/abs/2608.10509); Graphiti's cross-group contamination bugs are literally confidentiality failures (above). Enterprise multi-tenant agent platforms need it.
- **Overlap:** MEDIUM. In-event: accesscut (access revocation) is adjacent; I found nobody doing joint labels **[U - census based on READMEs]**.
- **Feasibility:** 3-4/5 *if scoped* to two label kinds: `integrity ∈ {trusted, untrusted, revoked}` and `confidentiality ∈ set of tenant/role tags`, propagated as property computations over `DERIVED_FROM`. Demo 4/5 ("agent B asked to include HR data in a public README: **blocked**, path shown").
- **Verdict:** this is the **framing** that lifts (a) from "another repair tool" to "an information-flow ledger for agents". Build integrity first; confidentiality as the second scenario (P1). Don't promise full IFC.

## 5. Other candidates considered
| Candidate | Evidence | Why not flagship |
|---|---|---|
| (e) Agent-config supply-chain forensics (rules files, skills, MCP descriptions with hashes; rug-pull detection) | Pillar, Invariant (above) | Static scanners already exist (MCP-Scan, Rule File Scanner https://rule-scan.pillar.security/); the *lineage* of what an infected rule caused is the novel part, which is candidate (a). **Use as demo scenario #3.** |
| (f) Procedural-memory verification (skills validated by outcomes) | "nodus"-style lessons entries in census | Hard to evaluate honestly in 3 days. |
| (g) Blast-radius / dependency impact | Organizer's own demo | ~13 clones. |
| (h) Company-brain with provenance | Track 3 | Needs real corporate-like data (rule 6), chatbot demo, ~6-7 clones. |

## 6. Ranking and recommendation
| Rank | Idea | Evidence | Novelty vs field | Feasibility | Demo | Verdict |
|---|---|---|---|---|---|---|
| 1 | **(a)+(d) Pedigree: capture-based information-flow ledger (taint + revoke + gate) for coding-agent memory, with (c) as tenant/concurrency suite and (b) as a feature** | strong | medium (engineering/eval novelty; algorithm not novel) | 4 | 5 | **Flagship** |
| 2 | (c) alone | medium | medium | 3 | 2 | Component |
| 3 | (b) alone | medium | low | 4 | 3 | Feature |
| 4 | (e) alone | strong | low-med | 4 | 4 | Demo scenario |

### Why the flagship beats generic RAG/chatbot-with-graph ideas
- It passes the organizer's own judging test: the product is **unusable without multi-hop** (depth-1 shows 2 affected items; depth-6 shows 31 incl. a commit) - this is the blog's "depth 1 vs depth 4" demo move, built into the core.
- It solves a problem judges (FalkorDB staff) know: agent memory plus Graphiti isolation pain.
- It is measurable (precision/recall/over-invalidation, unsafe-action rate, latency) - most entries show no numbers.
- It is a real artefact that plugs into tools Vedant actually uses (OpenCode, Claude Code, Cursor) = strong SDE-resume story (MCP server, hooks, multi-tenant DB design, security, tests, eval harness).

### Positioning against the nearest rivals (say this in README, kindly)
"Prior work (PACMI, MemoRepair, MAP-Graph) and other entrants model invalidation over provenance edges that are given. Pedigree's contribution is **capturing those edges from real agent sessions out-of-band**, **preserving independently supported beliefs**, **labelling both integrity and confidentiality**, and **measuring** the result."

### Flagship risks to say out loud
- Algorithm is known; judged on execution. If capture adapters flake, fall back to replaying recorded real traces (still real data, still honest).
- Session-level capture over-approximates influence (the agent "read" many things before acting). Report the over-approximation ratio; offer optional agent-supplied `cites` to tighten; show both in eval.
- Do not claim to *prevent* prompt injection; claim **containment, forensics and revert**.
