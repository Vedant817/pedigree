# Features, status, evidence

Status values: `todo` | `spec` | `implementing` | `qa` | `done` | `cut` | `blocked`.
A feature is `done` only when its tests pass **and** `docs/qa/F-nn.md` says PASS
(and `docs/qa/redteam-F-nn.md` PASS where it touches a trust boundary).
The README status table is generated from this file; never claim a feature in the README
that is not `done` here.

| ID | Pri | Feature | Status | Tests | QA report |
|---|---|---|---|---|---|
| F-01 | P0 | Repo skeleton, config, FalkorDB start/pin/health, schema (index+constraint), `graph_name()`, Makefile, secret scan | qa | tests/unit/test_config.py, tests/integration/test_schema.py | - |
| F-02 | P0 | Ingest engine: record_source / remember / record_action / corroborate; label inheritance; born-quarantined; parent validation | qa | tests/integration/test_core_scenario.py | - |
| F-03 | P0 | Revoke engine: barrier -> fixpoint -> `compute_final` -> chunked write -> verify; dry run; reinstate; resume; `check_invariants` | qa | tests/integration/test_core_scenario.py, tests/unit/test_compute.py | - |
| F-04 | P0 | Blame + impact (ancestors/descendants, shortest path via parent pointers, `not_in_graph`) | todo | - | - |
| F-05 | P0 | REST API + registry graph + tenant tokens + auth + limits + errors | todo | - | - |
| F-06 | P0 | MCP server (stdio + Streamable HTTP): record_source, remember, record_action, revoke, blame, impact | todo | - | - |
| F-07 | P0 | Claude Code hook adapter + `/v1/events` mapping + recorded-payload fixtures + cross-session `artifact_key` link | todo | - | - |
| F-08 | P0 | OpenCode plugin (`pedigree.ts`) mapped from real logged payloads | todo | - | - |
| F-09 | P0 | UI v1: graph view, status colours, revoke dry-run/confirm, depth slider, revert list | todo | - | - |
| F-10 | P0 | Scenarios S1 + S8 as JSON + `seed_demo.py` + `make demo` | todo | - | - |
| F-11 | P1 | Gate: `check_action` + REST `/v1/gate` + hook deny/ask + policy.yaml classifier | todo | - | - |
| F-12 | P1 | Confidentiality labels + scenario S6 | todo | - | - |
| F-13 | P1 | Isolation hardening: per-tenant ACL users, rate limits, quotas, metrics, structured logs | todo | - | - |
| F-14 | P1 | Eval harness: generator, independent oracle, baselines B0-B5, E1, E2, stats, NUMBERS pipeline | todo | - | - |
| F-15 | P1 | E5 isolation/concurrency suite (hypothesis + threads + invariants + ACL) | todo | - | - |
| F-16 | P1 | Deployment: Dockerfile (Ubuntu 24.04 single container), compose, Render, seed-on-boot | todo | - | - |
| F-17 | P2 | What-if (`GRAPH.COPY`) + checkpoint/restore | todo | - | - |
| F-18 | P2 | `audit_sources` (PageRank + descendant counts) | todo | - | - |
| F-19 | P2 | `supersede` (decision rot) + scenario S7 | todo | - | - |
| F-20 | P2 | Evals E3, E3b, E4, E4b, E6 + REPORT.md + eval sign-off | todo | - | - |
| F-21 | P2 | UI polish: path highlight, trace strip, taint animation, preserved badges | todo | - | - |
| F-22 | P2 | Hook spool/replay when the server is down | todo | - | - |
| F-23 | P3 | README, blog, demo video assets, AI disclosure, submission pack | todo | - | - |
