# 03 - Idea board (10 ideas, scored)

Scale 1-5 (5 best). Columns: **Nov** novelty vs field (incl. the in-event census), **Prob** real problem, **GraphN** graph necessity (breaks without FalkorDB / multi-hop), **Feas** solo 3-day feasibility with no card, **Wow** demo wow in 3 min, **Judge** appeal to FalkorDB/WeMakeDevs judges, **Resume** SDE-resume value, **Track** fit. Scores are my judgement (evidence in 01/02/06); total is an unweighted sum, then I apply a crowding penalty note.

| # | Idea | Nov | Prob | GraphN | Feas | Wow | Judge | Resume | Track | Sum | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Pedigree**: capture-based info-flow ledger for coding-agent memory (taint + revoke + gate, integrity & confidentiality; tenant graphs; MCP + hooks; eval) | 3 | 5 | 5 | 4 | 5 | 5 | 5 | 5 (T2, T1) | **37** | Crowded cluster but best differentiated; see 02 |
| 2 | Tenant-isolation & concurrency conformance harness for FalkorDB agent memory (Graphiti #1331/#1676 class) | 4 | 4 | 3 | 5 | 2 | 3 | 4 | 4 (T2) | 29 | Great *component*; weak solo demo |
| 3 | Agent-config supply-chain forensics (rules/skills/MCP descriptions, hash pinning, rug-pull -> blast radius to commits) | 3 | 5 | 4 | 4 | 4 | 4 | 4 | 3 (T1) | 31 | Scanners exist; fold into #1 as scenario |
| 4 | Decision-rot: assumptions graph, "which decisions rest on withdrawn assumption" | 2 | 4 | 4 | 4 | 3 | 3 | 3 | 4 (T3) | 27 | Crowded (ripple, decisiongraph, lineage); fold into #1 as `SUPERSEDES` |
| 5 | Blast-radius / RCA over service dependency graph (organizer demo clone) | 1 | 4 | 5 | 5 | 3 | 2 | 3 | 4 (T1) | 27 | ~13 clones; lowest differentiation |
| 6 | Company Brain with decision provenance + "who owns/knows" over public OSS org data (e.g. a real public repo's issues/PRs/ADRs) | 2 | 4 | 4 | 4 | 3 | 3 | 3 | 5 (T3) | 28 | ~6-7 clones; chatbot demo; data is public so rule 6 fine |
| 7 | Multi-agent handoff ledger: shared task graph with CAS versioning, claims/locks, handoff provenance | 3 | 4 | 3 | 3 | 3 | 3 | 4 | 5 (T2) | 28 | agentmesh/agent-office-relay overlap; coordination demo is dull |
| 8 | Procedural-memory ("skills") verified by outcomes: which learned skill/lesson caused which failures; auto-demote | 3 | 3 | 4 | 2 | 3 | 3 | 3 | 4 (T2) | 25 | Hard to evaluate honestly in 3 days |
| 9 | Codebase graph agent (call graph + git blame + PR history) answering "why does this code exist" for a public repo | 2 | 4 | 4 | 3 | 3 | 3 | 4 | 4 (T1) | 27 | Many code-graph tools exist (codemind in census); big data/parsing cost |
| 10 | Fraud-ring / security-alert triage on synthetic data | 1 | 3 | 4 | 4 | 3 | 2 | 2 | 4 (T1) | 23 | Track 1's own example; most common archetype |

## Final pick: **#1 Pedigree** (working name; no GitHub name collision seen in one search, re-check before creating the repo)
One-line pitch: **"git blame and git revert for what your AI agent believes - recorded automatically from real Claude Code / OpenCode / Cursor sessions, stored in FalkorDB, one graph per tenant."**

Absorbs: #3 (supply-chain scenario), #4 (SUPERSEDES), #2 (isolation suite).
Tracks: **Track 2 primary** (shared memory, per-tenant graphs, concurrency); **Track 1 secondary** (agent uses graph algorithms - closure, shortest path, PageRank, WCC, GRAPH.COPY what-if - as MCP tools to triage and act). Skip Track 3 unless the "decision/assumption" view is credible by Saturday night; confirm the track-count rule first (00 brief, section 3).
Side prize: blog post "How to un-poison an agent's memory" (AirPods).

### Scope ladder (cut from the bottom if time slips; ~78 h remain from 6 PM IST Thu)
- **P0 (must, by Fri night):** graph model; ingest API; closure/revoke with independent-support preservation; blame path; Claude Code hook OR OpenCode plugin capturing real sessions; 3 scenarios; one demo UI page (graph + revoke button + revert list); Docker Compose; README with data model + queries.
- **P1 (Sat):** pre-action gate (`check_action`) as MCP tool + hook that can block; per-tenant graph + bearer-token auth (MCP SDK `TokenVerifier`); eval E1/E2; tests; confidentiality labels + scenario #6.
- **P2 (Sat night / Sun):** `GRAPH.COPY` what-if; PageRank "load-bearing sources"; E3-E5; deployment; metrics endpoint (Prometheus-style counters + trace log).
- **P3 (Sun):** blog, video, polish, disclosure, rehearsal. **Freeze features Sun 3 PM IST.**
- **Cut order:** deployment polish -> ACL demo -> PageRank -> what-if -> confidentiality -> second runtime adapter. Never cut: real capture, eval numbers, video.
