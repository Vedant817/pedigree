# FIX PROMPT — paste this whole file into the OpenCode orchestrator (via T3 Code)

You are the **Orchestrator** for the repository `Vedant817/pedigree` (Pedigree: provenance, cascade-revoke and pre-action gate for AI-agent memory, on FalkorDB). An independent, evidence-based audit was run against commit `83de9da` (21 commits, 15 Oct 19:10–22:01 IST). Your job: **fix every finding below, in the priority order given, without regressing anything, and without fabricating a single number or QA result.** Read this entire file before starting.

## 0. Ground rules (non-negotiable)

**Clock (IST).** Hackathon: *WeMakeDevs × FalkorDB — Graph Hacks: Context for AI Agents*. **Feature freeze: Sun 18 Oct 15:00 IST. Submission deadline: Sun 18 Oct 23:59 IST.** After the freeze you may only fix bugs, docs, and submission assets. Record the current time (IST) in `docs/PROGRESS.md` at every milestone. If a phase will overrun its timebox by > 30 %, apply the cut order (§9) instead of grinding.

**Operating system.** Follow `docs/04-AGENT-OPERATING-SYSTEM.md` exactly (if the pack docs are not in `docs/`, they are in `docs/pack/`):
- Per-feature loop: SPEC (`docs/features/F-nn-*.md` or `docs/fixes/P-nnn.md`) → TESTS FIRST (show them failing for the right reason) → IMPLEMENT → SELF-REVIEW (`make check`) → **QA by `senior-qa` subagent with evidence** (commands + real output pasted into `docs/qa/…`, ≥ 5 adversarial cases, never edits `src/`) → **red-team** for anything touching auth/tenancy/input/Cypher/MCP/hooks/gate → DOCS → small commit `P-nnn: …` → PROGRESS entry.
- **Consult protocol at EVERY doubt** (`docs/consults/NNN-topic/question.md`): launch **three subagents in parallel** — `domain-researcher` (verifies external facts with a 30-second experiment on real FalkorDB v4.22.1), `senior-architect`, and one specialist: `red-team` (auth/tenancy/input/Cypher/MCP/hooks/gate/secrets), `devex-reviewer` (README/UI/onboarding/errors), or `eval-statistician` (benchmarks/numbers). Write `decision.md` + ADR in `docs/DECISIONS.md`. Cap 4 consults per phase; skip when the answer is already in `tech/` (cite the line).
- **QA must be independent.** A builder may not certify its own work. "Role-switch" verification is not allowed (the audit flagged F-01/F-07 for this). Every `docs/qa/*.md` must contain the exact commands, the real output, and a verdict; a 3-line "PASS" is invalid and will be treated as a defect.
- **Anti-fabrication.** No number in README, blog, video script, or docs unless it is produced by `make eval` and present in `docs/NUMBERS.md` (`scripts/check_numbers.py` must pass). If something was not run, write "not run". If something could not be verified, say so. Never write "tested on X" unless you ran it on X. Never invent a competitor claim; cite the file in `research/competitors/` or omit.
- **No secrets.** Nothing real in the tree or history. `scripts/secret_scan.py` (tree **and** `--history`) must pass before every push. Tokens never printed in logs/QA output (mask them). `.env` stays ignored.
- **FalkorDB pinned to v4.22.1** everywhere (compose, Dockerfile, CI, docs). Server flags: `TIMEOUT_MAX 60000`, `TIMEOUT_DEFAULT 20000`, `QUERY_MEM_CAPACITY` bounded. Any query timeout > `TIMEOUT_MAX` is rejected by the server — validate settings against it.
- **LLM never writes Cypher.** Static, parameterised Cypher only, in `db/queries.py`; the lint test must keep passing (and gets stricter in P-010).
- **Pushes:** `git push` only at the checkpoints in §10, and only after `make check` + clean-clone check pass. **Never make the repo public yourself — that is a human step.**
- Never commit raw outputs larger than 1 MB; eval raw data stays in `evals/results/raw/` (ignored); CSV/MD results are committed.

## 1. Context you must internalise (audit evidence)

Good (do not break): static parameterised Cypher + lint test; CAS barrier `Q_REVOKE_ROOT` → quarantine fixpoint → `compute_final` → chunked `Q_WRITE_FINAL` → verify; tenant isolation at API (cross-tenant → 404); gate decisions allow/warn/reverify/block with ADR-007 (trust only from human/scanner corroboration); Claude hook fail-open with 1 s timeout; 254 tests pass in ~9.6 s without flakiness; honest `docs/KNOWN_ISSUES.md`.

Broken (fix): see phases. Baseline to preserve: `pytest -q` → 254 passed; `scripts/check_numbers.py` PASS; `scripts/secret_scan.py` PASS.

---

## PHASE A — Unblockers that are cheap and unlock everything (Fri 16 Oct, timebox 4 h)

### A1 · P-010 — Kill the O(N²) label scans  *(do this first; 1 h)*
**Bug.** `src/pedigree/db/queries.py` lines ≈159 (`Q_SUPPORT_OF`), 162 (`Q_ACTION_DETAILS`), 166 (`Q_MEMORY_ARTIFACTS`), 297 (`Q_GATE_SUPPORT`) use `UNWIND $ids AS i MATCH (m:Memory {id:i}) …`. The unique index is on `:Node(id)`, so `EXPLAIN` shows *Node By Label Scan* → quadratic. Measured on a 60k-node graph, 1000 ids: 3.7–5.5 s each versus **0.01 s** for `MATCH (m:Node {id:i}) WHERE m:Memory`. Revoke cascade: 2k nodes 1.1 s, 5k 7 s, 10k 32 s, ≥ 20k times out.
**Fix.** Rewrite every `MATCH (x:Label {id:…})` that is driven by `UNWIND`/params into `MATCH (x:Node {id:…}) WHERE x:Label` (audit all of `queries.py`, not just these four). Keep semantics identical.
**Tests first.**
1. `tests/unit/test_query_lint.py`: fail if any query matches regex `MATCH \((\w+):(Memory|Action|Source|Session|Agent|Revocation) \{id` (anchor lookups must be on `:Node`).
2. `tests/perf/test_revoke_scaling.py` (marker `perf`, run in `make check-perf`): build a 20 000-node DAG (use bulk `UNWIND … CREATE`), revoke a root with ≥ 5 000 descendants, assert completes < 20 s and `check_invariants == []`. Also gate `check_action` with 10 relied-on ids on a 60k graph < 100 ms.
3. `EXPLAIN` test: for each rewritten query assert the plan contains `Node By Index Scan` and not `Node By Label Scan`.
**Acceptance:** all above pass; QA re-runs `EXPLAIN` on every query in `queries.py` and pastes the plans in `docs/qa/P-010.md`.

### A2 · P-016 — Fix `pedigree mcp` and mount `/mcp`  *(1–2 h)*
**Bug.** `src/pedigree/cli.py:180` calls `build_mcp(settings, default_tenant_id=…, default_tenant_token=…)` but `mcp_server.py:208` signature is `build_mcp(db=None, settings=None, …)`; result: `AttributeError: 'Settings' object has no attribute 'try_query'`. `opencode.json` and README claim `http://127.0.0.1:8000/mcp` but `api/app.py` mounts no MCP; `GET /mcp` → 404.
**Fix.** Use keyword args; mount the streamable-HTTP MCP app at `/mcp` in the FastAPI app (or run a documented second port and fix `opencode.json`/README/FEATURES accordingly — pick one via a 3-way consult).
**Tests first.** (a) subprocess test launching `python -m pedigree.cli mcp --transport stdio` and calling `record_source`+`blame` through the real `mcp` client; (b) HTTP test: real MCP client against the running API at `/mcp`; (c) a test asserting the URL in `opencode.json` answers an MCP `initialize`.
**Acceptance:** all three pass on a clean clone; `docs/qa/P-016.md` includes the real client transcripts.

### A3 · P-013 — Admin auth  *(45 min; red-team required)*
**Bug.** `api/routes/admin.py` lines 10 and 20: when the registry has no tenants, `/admin/tenants` (POST and GET) skip the admin check. A fresh deploy is owned by the first caller. Admin token compared with `!=`. `.env.example` ships `PEDIGREE_ADMIN_TOKEN=change-me-admin`.
**Fix.** Always require the admin token; refuse to start (non-dev) if `PEDIGREE_ADMIN_TOKEN` is empty or equals a known default; compare with `hmac.compare_digest`. Provide `pedigree admin create-tenant` CLI that reads the token from env for first-run.
**Tests.** fresh registry + no header → 401 (POST and GET); wrong token → 401; correct → 200; startup refuses default token when `PEDIGREE_ENV!=dev`.
**Acceptance:** red-team report `docs/qa/redteam-P-013.md` with real requests/responses.

### A4 · P-025 — No DB side effects on import  *(1 h)*
**Bug.** `api/app.py:82 app = create_app()` and `mcp_server.py:214–225 _build_default()` connect and create indexes at import; with the DB down `python -c "import pedigree.api.app"` raises `RuntimeError: index creation failed … Connection refused`.
**Fix.** `uvicorn pedigree.api.app:create_app --factory`; lazy default MCP server. Update CLI `serve`, Makefile, README, Docker CMD.
**Test.** `FALKOR_PORT=1 python -c "import pedigree.api.app, pedigree.mcp_server"` exits 0.

**Checkpoint A (push, tag `phase-A`):** `make check` green; perf test green; MCP stdio + HTTP green; update `docs/PROGRESS.md`.

---

## PHASE B — Revoke correctness & recovery (timebox 7 h; Fri 16 Oct)

### B1 · P-011 — Make a failed/crashed revoke recoverable  *(2 h)*
**Bug.** `engine/revoke.py:136` returns `{"idempotent": True}` when root is `revoked`/`running`; `resume_incomplete` (`revoke.py:299`) is never invoked outside tests. A 20k-node revoke that times out leaves nodes `quarantined` and `Revocation.status = running`; calling `revoke()` again is a no-op → permanently stuck.
**Fix.** `revoke()` first resumes any `running` Revocation for the tenant (under the tenant lock/CAS); the idempotent branch must resume when status is `running`; call `resume_incomplete` on app startup for every tenant (background, bounded) and expose `POST /v1/admin/resume` + `pedigree resume`. Chunk writes must be restartable.
**Tests first.** (1) fault injection: monkeypatch the writer to raise after chunk 1 of 3 → state shows `running` → call `revoke()` again → final statuses equal the oracle and Revocation is `done`; (2) kill-the-process test (subprocess killed mid-write, restart, resume); (3) crash between barrier and fixpoint.
**Acceptance:** oracle equality in all three; `check_invariants == []`.

### B2 · P-012 — `reinstate` must not un-revoke other roots  *(3–4 h; consult mandatory: domain + architect + eval-statistician-style oracle review)*
**Bug (deterministic repro).** `A(source) → B(memory) → Cc(memory)`; `revoke(A)`; `revoke(B)`; `reinstate(A)` → statuses `A=ok, B=ok, Cc=ok`. Expected `A=ok, B=revoked, Cc=tainted`. 22 of 150 random DAG trials diverge from an independent oracle. `check_invariants` does not detect it.
**Fix.** After removing the Revocation, recompute statuses for the affected subtree with `compute_final` using **all remaining active revocations and any node individually marked revoked** as roots; never set a revoked root to `ok`.
**Tests first.** The repro above; a `hypothesis` property test: random DAG, random sequence of revoke/reinstate/corroborate on up to 6 roots, after each step compare every node status to a **from-scratch global oracle** (`tests/oracle.py`, no shared code with `engine/compute.py`); extend `check_invariants` with "no node is `ok`/`preserved` while being a revoked root or having a revoked ancestor lacking trusted support".
**Acceptance:** 300+ hypothesis examples green, repro green, invariant extension catches the old bug (test that reverting the fix fails the invariant).

### B3 · P-024 — Reconcile children born during/after a revoke  *(2 h)*
**Bug.** Under concurrent writes, nodes created during a revoke stay `quarantined` forever (threaded probe: 54/358 nodes in one run; 0 leaks of `ok`/`preserved`, so safe but wrong).
**Fix.** After the verify step (and in `resume`), select `quarantined` nodes with no running revocation and run `compute_final` on them; add `pedigree reconcile`; add invariant "no `quarantined` node without a `running` Revocation".
**Test.** threaded writers + revoke (12 runs) → after reconcile, zero `quarantined`, statuses equal oracle.

### B4 · P-031 — Restrict `derived_from` parents to Source/Memory/Action  *(30 min)*
**Bug.** Session and Revocation nodes are accepted as parents. **Test:** 422/`invalid_argument` for them.

**Checkpoint B (push, tag `phase-B`).**

---

## PHASE C — Security hardening (timebox 7 h; Fri 16 – Sat 17 Oct; red-team subagent on every item)

### C1 · P-015 — Role separation: agent vs operator  *(3 h; consult mandatory with red-team)*
**Bug.** Probe: with one bearer token, `corroborate(by="human")` on a self-minted `Source(kind="human", integrity="trusted")` flips a poisoned memory from `tainted` to `preserved` after revoke and downgrades the gate from *block* to *reverify*. MCP tools and REST share one token with revoke/reinstate/corroborate power, so a prompt-injected agent has operator powers. `docs/KNOWN_ISSUES.md #11` calls this "accepted" — it is not acceptable for a security-themed product.
**Fix.** Two token roles per tenant: `agent` (ingest events/sources/memories/actions, read/blame/impact/gate) and `operator` (revoke, reinstate, corroborate with `by=human|scanner`, mint `integrity=trusted` sources, tenant admin). MCP and the hook use the `agent` token only; UI uses `operator`. Tokens carry the role prefix (`ped_a_…`/`ped_o_…`) and are stored hashed. Agent-role requests asserting `by=human|scanner` or `integrity=trusted` → 403.
**Tests.** the laundering repro now fails with 403; agent token cannot revoke/reinstate via REST or MCP; operator token can; existing tests migrated.
**Acceptance:** `docs/qa/redteam-P-015.md` with the attack transcript before/after.

### C2 · P-014 — Enforce quotas on every write path  *(1.5 h)*
**Bug.** `/v1/events` bypasses `node_cap` (cap 5 → 55 nodes in one request); sessions/corroborations unchecked. **Fix.** one `enforce_quota(tenant, add=n)` in the ingest engine, used by all paths, atomic per request. **Test:** events batch exceeding cap → 429/`quota_exceeded`, no partial write.

### C3 · P-021 — Strict input validation, no exception leaks  *(2 h)*
**Bug.** `/v1/events` with `"conf": 5` or `"artifacts": 5` → HTTP 500 and body `{"message":"'int' object is not iterable"}`; `derived_from:"abc"` iterated per character; NUL/newline in `uri` → `database error`; generic handler returns `str(exc)` (`api/app.py:33`, `mcp_server.py:25`).
**Fix.** Pydantic models (`extra="forbid"`, `list[str]` with item regex, bounded lengths, strip control chars from `uri`/`text` or reject); the generic handler returns `{"code":"internal","correlation_id":…}` only and logs the detail server-side.
**Tests.** table-driven: every malformed event shape → 422 with code `invalid_argument`, never 500; no response body contains a Python exception string.

### C4 · P-020 — Correct rate limiting; O(1) auth  *(2 h)*
**Bug.** writes count twice (60/min allowed vs 120 advertised); reads share the write bucket; `registry.resolve` loops over all tenants on a miss (3 ms → 75 ms at 307 tenants); no failed-auth throttle.
**Fix.** index tokens by SHA-256 digest (direct lookup); separate read/write buckets; per-IP failed-auth backoff (e.g. 10 failures/min → 429); document per-process limits.
**Tests.** exactly N allowed then 429; invalid-token latency constant (< 10 ms at 1 000 tenants); failed-auth throttle.

### C5 · P-029 — Small hygiene  *(1 h)*
`Bearer␠␠token` must be 401; admin tenant ids validated with the graph-name regex; `node_cap ≥ 1`; validate `FALKOR_*_TIMEOUT_MS ≤ 60000`; `/metrics` behind the operator/admin token; `/docs` disabled unless `PEDIGREE_ENV=dev` or `PEDIGREE_PUBLIC_DOCS=1`.

### C6 · P-036 — Document the trust model
Add `SECURITY.md` (threat model: prompt-injected agent, malicious tenant, hook spoofing; what is and isn't defended; responsible-disclosure email placeholder for the human). Update `KNOWN_ISSUES.md` honestly.

**Checkpoint C (push, tag `phase-C`):** `tests/security/` all green; red-team final report for C1–C5.

---

## PHASE D — Runnable by a judge in 5 minutes + deployable (timebox 6 h; Sat 17 Oct AM)

### D1 · P-004 + P-003 — Docker, compose, and a working no-Docker path
**Bug.** No `Dockerfile`/`docker-compose.yml`/`render.yaml`; KNOWN_ISSUES #1 and ADR-001 reference a "production Dockerfile" that doesn't exist. README `make start-db` on Linux without Docker fails (needs activated venv, the `localdb` extra and `FALKOR_SO`, none documented); README serve command is Windows-only (`.venv/Scripts/python.exe`).
**Deliver.**
- `Dockerfile` (python:3.12-slim, non-root, `HEALTHCHECK` on `/readyz`, `CMD uvicorn pedigree.api.app:create_app --factory`).
- `docker-compose.yml`: services `falkordb` (`falkordb/falkordb:v4.22.1`, flags TIMEOUT_MAX/DEFAULT/QUERY_MEM_CAPACITY, volume) + `pedigree`; seed-on-boot of the synthetic demo tenant (idempotent), **admin disabled for the public demo tenant**; `docker compose up` → UI at `http://localhost:8000`, printed demo operator token for local only.
- `make quickstart` (no Docker): installs with `.[localdb]`, starts the lite server, seeds, serves — works from a clean `python:3.12` container on Linux/macOS; separate `make quickstart-windows` or a documented PowerShell snippet.
- Optional (if time): one public deploy (Render/Fly) with a **read-only demo tenant**; put its URL in README only after `curl` verifies it.
**Tests/acceptance.** `scripts/clean_clone_check.sh` runs in a fresh container and in CI; QA subagent follows the README *literally* from a clean clone on Linux and records every command + output in `docs/qa/P-003.md`. Any step that fails → fix the README or the code, re-run.

### D2 · P-028 — Reproducible environment + CI
Lockfile (`uv lock` or `pip-compile --generate-hashes` → committed), pinned `falkordb` client, `.github/workflows/ci.yml` (matrix: Python 3.12; service `falkordb/falkordb:v4.22.1`; runs `make check`, `check_numbers`, `secret_scan`, perf-lite), README badge.

**Checkpoint D (push, tag `phase-D`).**

---

## PHASE E — Evaluation: the numbers that differentiate us (timebox 8 h; Sat 17 Oct)

### E1 · P-006 — Minimum viable honest eval (F-14 subset; follow `docs/03-EVAL-AND-DEMO.md`)
**Gap.** No `evals/`, no baselines, no numbers; `AI_DISCLOSURE.md` cites a nonexistent `evals/baselines.py`.
**Deliver (minimum):**
- `evals/generate.py` — seeded synthetic coding-agent lineage graphs (sizes 1k, 10k, 100k nodes; fan-in/out distributions documented; 20 seeds).
- `evals/oracle.py` — independent global-fixpoint ground truth (shares **no** code with `engine/`).
- `evals/baselines.py` — B0 *no tracking*, B1 *revoke only the poisoned node*, B2 *time-window quarantine (everything after the poison)*, B3 *naive full-descendant delete*; Pedigree = our engine. Baselines must be given the same information as a reasonable engineer would have — document each, and have the `eval-statistician` try to make them **stronger**.
- **E1 containment:** precision/recall of the affected-set vs oracle, over-quarantine rate, preserved-support correctness; mean + 95 % bootstrap CI over seeds.
- **E2 latency scaling:** revoke/blame/gate latency vs N (p50/p95), memory, on FalkorDB v4.22.1 — this is where P-010 pays off; report the real curve, including if it is worse than hoped.
- `make eval` → `evals/results/*.csv` + `evals/REPORT.md` → `scripts/make_numbers.py` writes `docs/NUMBERS.md` → README/blog/video pull numbers via `check_numbers`. The `eval-statistician` must write a SIGN-OFF in `docs/qa/eval-signoff.md` (threats to validity: synthetic data, oracle shares our semantics, single machine).
**Acceptance:** `make eval` reproduces within CI on a clean clone; `check_numbers` passes; if Pedigree does **not** beat a baseline on some metric, the report says so.

### E2 · P-022 — Observability and visible tool-call trace
- Return `trace` (list of `{op, ms, rows}`) from `/v1/revoke`, `/v1/blame`, `/v1/impact`, `/v1/gate` and the MCP tools (the `Trace` object already exists in `db/client.py`; routes never pass it).
- `/metrics`: `pedigree_query_seconds{op}`, `pedigree_revocations_total{status}`, `pedigree_gate_decisions_total{decision}`, `pedigree_nodes{tenant,status}`; protected.
- JSON structured logs (`request_id`, tenant, op, ms) via stdlib `logging`; no tokens in logs (test greps for token patterns).
- UI: trace strip under the graph (collapsible) showing the ops of the last action.
**Tests.** response contains `trace` with ≥ 1 op; metrics series exist after one revoke; log lines parse as JSON and contain no `ped_` token.

### E3 · P-023 — Isolation & concurrency suite (F-15 subset)
`tests/isolation/`: `hypothesis` multi-tenant interleavings; threaded revoke/ingest across 2 tenants; assert no cross-tenant read/write/leak via REST + MCP + hook; a test per route that tenant B's token against tenant A's ids → 404. Optionally FalkorDB ACL users per tenant (only if time remains; consult).

**Checkpoint E (push, tag `phase-E`).**

---

## PHASE F — Real capture + demo that survives a skeptical judge (timebox 6 h; Sat 17 Oct PM)

### F1 · P-017 — Capture from real sessions
**Gap.** All hook tests use hand-written payloads; `tests/fixtures` doesn't exist though F-07 promised recorded fixtures; WebFetch/WebSearch aren't mapped to Sources; Bash reads aren't edges; session-wide taint makes later benign actions `ask`; `\bssh\b` regex flags `cat ~/.ssh/config` as irreversible/high.
**Deliver.**
- *(Human-only, 20 min — see §11)* record 2–3 real Claude Code sessions with the hook in log-only mode; place sanitised JSONL in `tests/fixtures/claude/`. Until then, mark the adapter "validated on synthetic payloads only" in README.
- Fixture-replay tests against those recordings.
- Map `WebFetch`/`WebSearch` → `Source(kind=web, integrity=untrusted)`; `Bash` with `cat|head|curl|wget` on a path/URL → `READ` edges; `Read` → READ.
- Narrow taint: a session is "tainted" only if it READ a node that is now revoked/tainted, not by mere same-session timing.
- Tighten classifier regexes (word-boundary + path-aware); add unit tests incl. the `.ssh` false positive.
- F-08 OpenCode adapter: **only if the model/provider quota works**; otherwise leave `blocked` with the documented reason. Do **not** burn time here.

### F2 · P-027 — Demo scenario with enough substance
- Second seed tenant `demo-realistic` (~300 nodes, 40+ actions) generated from a synthetic coding-agent trace (poisoned README fetched → memory "use curl|sh installer" → derived memories → `git push --force` attempt blocked).
- UI: blame path highlight, one-click demo login for the **read-only** demo tenant (token injected server-side for the demo URL only), "Revoke this source" animation; trace strip from E2.
- Screenshot + 20-second GIF into `docs/assets/` (human can re-record; generate with headless Chrome if possible).
**Acceptance:** `docs/qa/F2.md`: QA follows the demo script step by step, records real outputs/screenshots; the demo runs end-to-end in < 3 minutes.

**FEATURE FREEZE: Sun 18 Oct 15:00 IST.** Everything after is bugs/docs/assets.

---

## PHASE G — Docs, honesty, process cleanup (timebox 6 h; Sat night → Sun noon; run in parallel with F by a separate builder on `docs/*` only)

### G1 · P-002 — README to hackathon standard
First screen (above the fold): one-sentence pitch; badge row (CI); 20-s GIF; **three measured numbers from `docs/NUMBERS.md`** (never hand-typed); 3-command quickstart (compose) + no-Docker path.
Required sections: **Problem & why a graph**; **Architecture diagram** (Mermaid); **Graph data model** (Mermaid ER + property table for Source/Memory/Action/Session/Agent/Revocation and DERIVED_FROM/FEEDS/CORROBORATED_BY/READ; one graph per tenant `ped:<tenant>`; registry graph; `:Node(id)` unique constraint + index and *why* queries must anchor on `:Node`); **Cypher & algorithms** (verbatim: revoke-root CAS, quarantine fixpoint, `compute_final` support-preserving rule, blame shortest-path, gate decision; with a paragraph on each and complexity); **Interfaces** (REST, MCP, hook, UI); **Tracks entered**; **Evaluation** (link `evals/REPORT.md`; threats to validity); **Security model** (link `SECURITY.md`); **Limitations** (link `KNOWN_ISSUES.md`); **AI disclosure** (link); **License**.
`scripts/check_readme.py`: fails if any of those headings is missing, if a `docs/*.md` link is dead, or if a number in the README isn't in `NUMBERS.md`.

### G2 · P-005 — WALKTHROUGH, demo script, blog draft
- `docs/WALKTHROUGH.md` — human-explainability doc: 1 page on the revoke barrier + fixpoint in plain language, with a worked 6-node example and the exact Cypher at each step, so Vedant can explain it cold on camera (hackathon Rule 12/13).
- `docs/DEMO_SCRIPT.md` — 3-minute video script with timestamps, on-screen commands, narration, fallback if the live demo fails; every number sourced from `NUMBERS.md`.
- `docs/BLOG.md` — 800–1200-word draft (problem, model, the O(N²) lesson and 300× fix, eval results, limitations); marked DRAFT for the human to edit.

### G3 · P-030 — AI disclosure that will survive scrutiny
Rewrite `AI_DISCLOSURE.md` as a **fact sheet**: tools/models actually used (the human confirms exact names), what was AI-generated (explicitly: **the design pack and the core-engine prototype that seeded commit `d7b3d22` were AI-generated before coding began**), what the human did (leave clearly-marked fields for Vedant to fill in his own words — do **not** invent them), remove every reference to files that don't exist.

### G4 · P-007 — Re-do QA properly
For F-03, F-05, F-06, F-07 produce real `docs/qa/*.md` (commands + real output + ≥ 5 adversarial cases each). Remove "role-switch" claims. Update `docs/FEATURES.md` so a feature is `done` only with valid QA; downgrade any that fail.

### G5 · P-032..P-035 — Hygiene
Remove dead code (`REGISTRY_GRAPH`, `Q_PAGERANK_SOURCES`, unused LLM settings) or implement; fix the PROGRESS references to the missing `phase-0`/`fd948a0` (re-tag at the real commit and note the history was re-created); add `LICENSE` check, `CONTRIBUTING.md`, issue/PR templates; tag `v0.1.0`; move `docs/pack/*` and competitor research into `docs/design/` (human decides whether to publish strategy docs — default: keep design docs, drop `research/competitors/` from the public tree).

---

## PHASE H — Final release gate (Sun 18 Oct 12:00–15:00 IST; then freeze)

Run in this order and stop on the first failure:
1. `make check`, `make check-perf`, `make eval`, `python scripts/check_numbers.py`, `python scripts/check_readme.py`, `python scripts/secret_scan.py` and `--history` (plus `gitleaks detect` if installed).
2. `devex-reviewer` clean-clone test **literally following the README** on Linux (fresh container) — `docs/qa/devex-final.md` with every command and output.
3. `red-team` final pass on trust boundaries — `docs/qa/redteam-final.md`.
4. `eval-statistician` SIGN-OFF on `NUMBERS.md`.
5. Re-run the audit probes in `tests/qa/probes/` (copied from the audit) — all must pass: label-scan lint, stuck-revoke recovery, reinstate oracle, admin bootstrap, quota, laundering (403), malformed events (422), import without DB.
6. Update `docs/PROGRESS.md` CURRENT STATE and `docs/FEATURES.md` truthfully.

## 9. Priority order and cut list

**Must (never cut):** A1–A4, B1–B3, C1–C4, D1, E1 (E1+E2 minimum), E2 trace, G1–G3, H.
**Cut in this order if time runs short:** F-22 → F-19 → F-21 extras → F-17 checkpoints → F-18 → E4b → F-12 → second runtime adapter (F-08) → E3b → optional public deploy → ACL users (E3 optional part) → F2 animation.

## 10. Push checkpoints (Fri 16 – Sun 18 Oct IST)
Fri night: `phase-A`, `phase-B` · Sat midday: `phase-C`, `phase-D` · Sat night: `phase-E` · Sun 15:00 freeze: `phase-F`+`phase-G` · Sun 15:00–20:00: Phase H and fixes only · Sun 20:00: final tag `v1.0.0-submission`, then **stop pushing** and wait for the human.

## 11. DO NOT
- Do **not** invent, round up, or hand-edit any benchmark number, QA result, competitor claim, test count, or "tested on" statement.
- Do **not** self-certify QA, edit `src/` from the QA role, or mark a feature `done` without a valid QA report.
- Do **not** weaken or delete a failing test to get green; fix the code or document the limitation in `KNOWN_ISSUES.md`.
- Do **not** add new features before Phase H is green except those listed here; no new dependencies without a consult; no torch/large downloads (disk is limited).
- Do **not** let the LLM or any adapter construct Cypher; do **not** build queries by string concatenation.
- Do **not** commit secrets, real tokens, `.env`, key-shaped strings (mask synthetic ones in tests), or the demo token file.
- Do **not** bump the FalkorDB pin; do **not** use `MULTI/EXEC`; do **not** pass query timeouts above `TIMEOUT_MAX`.
- Do **not** make the repo public, post anywhere, email anyone, record the video, or write the human-voice parts of the disclosure/blog final text.
- Do **not** claim the OpenCode adapter works unless a real session payload was captured (F-08 is blocked on provider quota; say so).
- Do **not** rewrite git history again; if history must be corrected, stop and ask the human.

## 12. Final submission checklist (the orchestrator ticks each with evidence in `docs/PROGRESS.md`)
- [ ] Repo **public** (human) — after `secret_scan --history` and gitleaks are clean.
- [ ] README has: first-screen pitch + GIF + 3 measured numbers; data model; Cypher & algorithms; architecture; setup that works from a clean clone (compose + no-Docker); tracks named; evaluation + limitations; security model; AI disclosure link; license.
- [ ] `docs/WALKTHROUGH.md` exists and Vedant has read it and can explain the barrier/fixpoint without notes.
- [ ] `docs/DEMO_SCRIPT.md` final; video recorded (human), ≤ 3 min, uploaded, link in README.
- [ ] Live demo URL **or** verified local instructions (preferably both); URL `curl`-checked.
- [ ] `AI_DISCLOSURE.md` complete, human-written parts filled in by Vedant, pack/prototype origin stated, no references to missing files.
- [ ] Blog published (human) — numbers from `NUMBERS.md` only.
- [ ] `make eval` reproducible; `NUMBERS.md` signed off; `check_numbers` passes.
- [ ] CI green on `main`; lockfile committed; `v1.0.0-submission` tag.
- [ ] `SECURITY.md`, `KNOWN_ISSUES.md` honest and current; LICENSE present.
- [ ] Hackathon form submitted (human) with repo URL, video URL, demo URL, tracks, team info.

## 13. Human-only list (put these in the final PROGRESS "human-pending" block; do not attempt)
1. Make the GitHub repo public (after the secret scans).
2. Record 2–3 real Claude Code sessions for fixtures (20 min) and approve sanitisation.
3. Fill in the "what the human did" part of `AI_DISCLOSURE.md` in his own words; confirm model/tool names.
4. Read `WALKTHROUGH.md`; rehearse; record and upload the demo video (≤ 3 min).
5. Edit and publish the blog (own voice).
6. Create any hosting account/billing for the public deploy; set `PEDIGREE_ADMIN_TOKEN` in the host's secret store.
7. Decide whether to publish `docs/design/` and competitor research.
8. Submit the hackathon form before Sun 18 Oct 23:59 IST; post socials if desired.
9. Switch the builder model/provider if the OpenCode free tier keeps stalling (F-08 was blocked on `free_tier_limit`).

**Start now with A1. Report after each checkpoint with: tests run (command + counts), QA report path, consult decisions, numbers produced, and the next three actions.**
