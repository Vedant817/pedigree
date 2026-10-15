# 05 - PHASES (time-boxed plan, all times IST)

Now: Thu Oct 15 2026 ~7 PM. Hard deadline: Sun Oct 18 11:59 PM. **Feature freeze: Sun 3:00 PM.** Target final submit: **Sun 9:00 PM** (2 h 59 m buffer). The agent runs continuously; the human is needed only at the checkpoints marked **[HUMAN]**.

## 0. Feature list and priority ladder
| Pri | ID | Feature |
|---|---|---|
| **P0** | F-01 | Repo skeleton, config, FalkorDB start/pin/health, schema (index+constraint), `graph_name()`, Makefile, secret scan |
| P0 | F-02 | Ingest engine: record_source / remember / record_action / corroborate; label inheritance; born-quarantined rule; validation of parents |
| P0 | F-03 | Revoke engine: barrier -> fixpoint -> `compute_final` -> chunked write -> verify; dry run; reinstate; resume; `check_invariants` |
| P0 | F-04 | Blame + impact (ancestors/descendants, shortest path via parent pointers, `not_in_graph`) |
| P0 | F-05 | REST API + registry graph + tenant tokens + auth + limits + errors |
| P0 | F-06 | MCP server (stdio + Streamable HTTP), tools: record_source, remember, record_action, revoke, blame, impact |
| P0 | F-07 | Claude Code hook adapter (`pedigree_hook.py`) + `/v1/events` mapping + recorded-payload fixtures + cross-session `artifact_key` link |
| P0 | F-08 | OpenCode plugin (`pedigree.ts`) mapped from the real logged payloads |
| P0 | F-09 | UI v1: graph view, status colours, revoke dry-run/confirm, depth slider, revert list |
| P0 | F-10 | Scenarios S1 + S8 as JSON + `seed_demo.py` + `make demo` |
| **P1** | F-11 | Gate: `check_action` + REST `/v1/gate` + hook deny/ask + policy.yaml classifier |
| P1 | F-12 | Confidentiality labels + scenario S6 |
| P1 | F-13 | Isolation hardening: per-tenant ACL users, rate limits, quotas, metrics, structured logs |
| P1 | F-14 | Eval harness: generator, independent oracle, baselines B0-B5, E1, E2, stats, NUMBERS pipeline |
| P1 | F-15 | E5 isolation/concurrency suite (hypothesis + threads + invariants + ACL) |
| P1 | F-16 | Deployment: Dockerfile (Ubuntu 24.04 single container), compose, Render, seed-on-boot |
| **P2** | F-17 | What-if (`GRAPH.COPY`) + checkpoint/restore |
| P2 | F-18 | `audit_sources` (PageRank + descendant counts) |
| P2 | F-19 | `supersede` (decision rot) + scenario S7 |
| P2 | F-20 | Evals E3, E3b, E4, E4b, E6 + REPORT.md + eval sign-off |
| P2 | F-21 | UI polish: path highlight, trace strip, animation of taint wave, preserved badges |
| P2 | F-22 | Hook spool/replay when the server is down |
| **P3** | F-23 | README, blog, demo video assets, AI disclosure, submission pack |
**Cut order (when behind, cut from the top of this list first):** F-22 -> F-19 -> F-21 extras -> F-17 checkpoints (keep what-if) -> F-18 -> E4b -> F-12 (keep S6 only if gate done) -> second runtime adapter (keep Claude Code OR OpenCode, whichever works better) -> E3b. **Never cut:** F-01..F-07, F-09, F-10, F-11, F-14 (E1+E2), F-15, F-16 (at least local), real capture from one runtime, NUMBERS pipeline, the video, the blog.

## Phase 0 - Foundation and spikes  (Thu 7:00 PM -> 11:30 PM; 4.5 h)
Work: F-01, start F-02/F-03 by porting `tech/examples/py/12_pedigree_core.py` into `src/pedigree/` with tests. **Spikes (each <= 30 min, consult protocol if blocked, result in `docs/consults/`):**
- S-A MCP: mount in FastAPI + bearer is ALREADY VERIFIED (`tech/examples/mcp/mount_in_fastapi.py`, mcp 2.3.0); spike = adapt it (tenant via contextvar) and confirm OpenCode connects to it over HTTP with a bearer header (`{env:MCP_TOKEN}`). Fallback: stdio server.
- S-B OpenCode: log real `tool.execute.after` `input`/`output` JSON to `docs/consults/opencode-after-shape.json` from a throwaway session.
- S-C Claude Code (if installed on the human's machine; else use docs payloads as fixtures): confirm matcher syntax (`*`), `permissionDecision` values (`deny|ask|allow`), `type:http`.
- S-D Install check on a clean venv: total size of `pip install -e .[dev]` (no torch).
**[HUMAN] checkpoint 0 (batched, ~20 min):** GitHub repo + push access, `.env` keys (see 00-HUMAN-CHECKLIST), enable the OpenCode capture plugin so Friday's build sessions are recorded (E6 corpus).
**Acceptance tests (phase 0):**
- AT0.1 `make start-db` starts FalkorDB; `MODULE LIST` shows graph module ver 42201 (v4.22.1).
- AT0.2 `make test` green incl. ported scenario test (tainted/preserved/ok mix, idempotent revoke, blame chain, race hook test, born-quarantined test).
- AT0.3 schema creation idempotent; unique constraint rejects duplicate id; index OPERATIONAL wait helper.
- AT0.4 `graph_name('abc') == 'ped:abc'`; invalid tenant ids rejected (`ab`, `ABC`, `a_b`, `abc:x`, 25 chars, empty).
- AT0.5 `check_invariants` passes after the scenario and **fails** on a hand-corrupted graph (negative test).
- AT0.6 `scripts/clean_clone_check.sh` (fresh clone + venv + tests) passes.

## Phase 1 - P0 vertical slice (Fri 9:00 AM -> 9:00 PM; 12 h)
Work: F-02..F-10. Capture adapters first (so real traces start accumulating), then API/MCP, then UI.
**Acceptance tests:**
- AT1.1 E2E: replay `tests/fixtures/claude_session_01.jsonl` (recorded hook payloads) through `pedigree_hook.py` -> `/v1/events` -> graph: expected Source/Memory/Action counts; cross-session link via `artifact_key` (session B reads the memory file written in session A and an Action's artifact).
- AT1.2 Revoke dry-run then real on the replayed session: expected tainted/preserved/ok sets; affected Actions incl. the irreversible `git push`; `blame` path ends at the revoked source.
- AT1.3 MCP: real client (`mcp` Client) calls all P0 tools over Streamable HTTP with a bearer token; wrong token -> `unauthorized`; unknown id -> `not_in_graph`.
- AT1.4 REST contract tests incl. every error code (422/401/404/409/413/429).
- AT1.5 UI: loads `/v1/graph`, shows colours by status, depth slider changes highlighted set, revoke button runs dry-run and then confirm; Playwright/e2e smoke **only if installable on the disk budget, else a scripted DOM test with `httpx` + static checks** (consult).
- AT1.6 Tenant isolation smoke: tenant A token cannot read B; B's graph unchanged after A's revoke.
- AT1.7 Dogfood: at least one real OpenCode/Claude Code session recorded into a dev tenant (count of events in PROGRESS).
- AT1.8 QA PASS files exist for F-02..F-10; red-team pass #1 on F-05/F-06/F-07 (auth, ids, limits).
**[HUMAN] checkpoint 1 (Fri ~9 PM, 10 min):** look at the UI, say go/no-go on scope; post the Discord question if not yet done.

## Phase 2 - P1 safety, gate, isolation, eval harness (Sat 9:00 AM -> 9:00 PM; 12 h; Fri 9 PM-midnight optional: F-14 skeleton overnight)
Work: F-11..F-16. **Early deploy spike Sat morning** (Render single-container) because it is the riskiest unverified step.
**Acceptance tests:**
- AT2.1 Gate matrix test: allow / warn / reverify / block for each decision rule, with reasons+paths; hook returns deny JSON for `block`; fail-open behaviour when server is down (documented + tested); `not_in_graph` -> reverify.
- AT2.2 Confidentiality: S6 blocked with path; audience superset allowed.
- AT2.3 Isolation: per-tenant ACL user cannot touch `ped:abcd` from `ped:abc` (uses 13_acl script pattern); hypothesis test with >= 20 tenants x 8 writer threads ends with all invariants OK and zero cross-tenant nodes.
- AT2.4 Limits: oversize body 413; array caps; rate limit 429 with Retry-After; node-cap `quota_exceeded`; query timeout produces `timeout` (test with an intentionally heavy query on a test graph).
- AT2.5 Observability: `/metrics` exposes the listed series; logs contain no token/text (grep test).
- AT2.6 E1 + E2 run end-to-end with N>=30 seeds per cell; `evals/oracle.py` agrees with `engine/compute.py` on 1000 random small DAGs; NUMBERS.md generated; **eval-statistician review of design** before the big run.
- AT2.7 Docker build succeeds on Render (or documented failure + local fallback), `/readyz` OK, demo tenant seeded on boot.
- AT2.8 Red-team pass #2 (gate, ACL, rate limit, MCP).
**[HUMAN] checkpoint 2 (Sat ~9 PM, 10 min):** confirm deploy URL works in a browser; decide tracks (see checklist) if not decided.

## Phase 3 - P2 features, remaining evals, polish (Sat 9:00 PM -> Sun 11:00 AM; overnight, agent-only)
Work: F-17..F-22 (apply cut order if behind), E3/E3b/E4/E4b/E6, scenarios S2-S7, UI polish, devex clean-clone review.
**Acceptance tests:**
- AT3.1 What-if on `GRAPH.COPY`: diff equals real revoke on the same graph; copy deleted in `finally`; max concurrent what-ifs enforced; stale copies reaped.
- AT3.2 `audit_sources` returns ranked sources with descendant counts that match BFS counts exactly.
- AT3.3 Scenarios S1-S8 pass E3 exact-match; E3b friction computed on recorded traces.
- AT3.4 E4 (sizes up to the disk-feasible max, capped at 1e6 nodes) + E4b SQLite comparison produce CSVs with machine info; E5 stress run clean.
- AT3.5 Eval statistician SIGN-OFF (or listed required changes done); `docs/NUMBERS.md` regenerated from scratch (`make eval`), diff-checked.
- AT3.6 Devex reviewer: clean clone to running demo <= 10 minutes following README only; P0 findings fixed.
- AT3.7 Red-team final pass: no open High/Critical.

## Phase 4 - Docs, blog, video assets, release candidate (Sun 11:00 AM -> 3:00 PM; **freeze at 3:00 PM**)
Work: F-23. docs/WALKTHROUGH.md (every demo click, tested step by step), docs/FEATURES.md, docs/KNOWN_ISSUES.md, README (data model + Cypher + algorithms + setup + limitations + tracks + disclosure), blog draft from `08-BLOG-TEMPLATE.md` with NUMBERS, demo script and shot list finalised from the *actual* UI, AI_DISCLOSURE.md, `scripts/check_numbers.py` passing, release tag `v1.0-submission`.
**Acceptance tests:** AT4.1 `scripts/check_numbers.py` PASS (every README/blog numeral in NUMBERS.md); AT4.2 clean-clone + local demo works from README; AT4.3 live URL smoke (`/readyz`, UI loads, MCP initialise); AT4.4 secret scan PASS on full git history; AT4.5 license + disclosure present; AT4.6 FEATURES.md matches README Status table.
**[HUMAN] checkpoint 4 (Sun ~1 PM):** read README/blog once; sanity-check every claim you cannot explain.

## Phase 5 - Human release window (Sun 3:00 PM -> 9:00 PM target; hard stop 11:59 PM)
- 3:00-4:30 PM: record the demo video (2 takes), upload to YouTube (unlisted OK).
- 4:30-5:30 PM: publish the blog (dev.to and/or where the organizers say), link the video.
- 5:30-6:30 PM: fill the submission form (fields unverified until you open it), double-check track names, repo URL, video URL, live URL.
- By **9:00 PM**: submitted. 9:00-11:59 PM: buffer only (fix typos, re-verify links). The agent, in parallel, performs bug-fixes only (no features) and re-runs the release checks after each fix.
Detailed T-minus list is in 00-HUMAN-CHECKLIST.md.

## Checkpoint protocol (every phase end)
1. Run phase acceptance tests on a clean clone; 2. tag `phase-N`; 3. update PROGRESS CURRENT STATE; 4. one-line status; 5. batched human message if needed; 6. check `date` vs plan and apply the cut order **now**, not later.
