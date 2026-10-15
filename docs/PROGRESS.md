# CURRENT STATE (overwritten after every feature / checkpoint)

- **Phase:** P2 -> P4 in parallel (Thu/Fri 02:40 IST). Phase 1 acceptance tests are met
  (AT1.1-AT1.6 verified; AT1.7 dogfood capture is quota-blocked and honestly recorded).
- **Last green implementation:** 41469e0 (F-14 E4 latency) + uncommitted E3/QA pass.
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.
- **Test state:** **300 passed, 1 skipped** (`make check`-equivalent; the skip is the ACL test
  without the deployment secret) | ruff PASS | secret scan `--history` PASS | numbers check PASS
  (README + blog + submission + walkthrough against 61 values in `docs/NUMBERS.md`).
  `make eval` 80 s, `make eval-quick` 4 s; the container boots and passes end-to-end.
- **Features [done]:** F-01..F-07 (QA PASS), F-09, F-10, F-11 (QA PASS), F-16 (QA PASS local),
  F-13/F-15 capture-trust and isolation scope (QA PASS with documented residuals),
  F-14 E1/E2/E3/E4 (numbers in NUMBERS.md; E4b/E5/E6 remain).
- **Local service:** demo tenant seeded (`scratch/demo-demo.json`, git-ignored; never print it).
- **Next 3 actions:**
  1. Remaining eval items: E4b (SQLite closure comparison) and the E5/E6 report entries.
  2. F-12 confidentiality scenario S6 + F-17 what-if and F-18 audit_sources (demo depth).
  3. Phase-4 pass: docs tidy, `clean_clone_check.sh` re-run, tags `phase-0..phase-4`, and the
     batched human message (repo remote, video, submission).
- **Blockers:** none open. OpenCode free provider quota (F-08) and provider rate limits for
  specialist subagents are recorded in the consults.
- **Human pending (batch 1 reply outstanding):** GitHub repo + remote URL, Discord answer,
  dogfood runtime choice, optional API keys in `.env`; Render account for the live URL.

---

### 2026-10-15 19:34-20:10 IST | Phase P0->P1 | F-04, F-05, F-06, security pass, F-07 | STATUS: done (F-07 QA gap)
- Landed F-04 blame+impact (`44c2635`; 14 tests; `docs/qa/F-04.md` PASS), F-05 REST API + tenant
  registry + bearer auth (`ae24a98`; `docs/qa/F-05.md` PASS), F-06 MCP stdio+streamable-http
  (`554a991`, `821c679`; `docs/qa/F-06.md` PASS), red-team/security hardening for F-05/F-06
  (`fb13e3a`: Content-Length validation, reserved `registry` tenant rejected, MCP token+quota,
  REST integrity literal, CLI `mcp`; 10 security tests), F-07 `/v1/events` + `adapters.py`
  normalisation + `/v1/artifacts/lookup` + `/v1/invariants` (`e17c956`, `8a45d0e`).
- Suite grew 62 -> 94 tests; `make check` green throughout; no PROGRESS entries were written for this
  stretch (documentation debt, reconciled in this entry).
- Gaps found while reconciling (fixed by the actions in CURRENT STATE): `docs/qa/F-07.md` never
  landed although FEATURES.md marks F-07 done; PROGRESS.md last entry was 19:55; F-11 prototype is
  uncommitted and non-conforming to §6.6.
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1; 108 GB free disk.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.

---

### 2026-10-15 19:55 IST | Phase P0 | F-01 close + phase-0 tagged | STATUS: done
- Fix shipped: `secret_scan.py --history` (UnicodeDecodeError -> utf-8/errors=replace), engine
  per-tenant validation (`validate_tenant` in config, called by record_source/remember/record_action/
  revoke/reinstate), new `Q_INV_MISSING_STATUS` invariant, extended static-Cypher lint detector,
  `scripts/check_secrets.sh` wrapper.
- Tests added: `tests/unit/test_secret_scan.py` (5), `tests/integration/test_tenant_guard.py` (7),
  `tests/integration/test_schema.py::test_invariants_detect_missing_status`.
- QA round 1 found 1 HIGH defect; round 2 verification PASS (role-switch after subagent rate-limit)
  - 62 passed, `make check` green, AT0.1-AT0.6, all scratch graphs cleaned.
- Tag `phase-0` on commit `fd948a0`. Next: F-04.
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1; 108 GB free disk.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.
- **Test state:** 45 passed (full suite incl. real-FalkorDB integration) | `make check` green
  (ruff + pytest + secret scan + numbers check) | AT0.1-AT0.5 verified; AT0.6 pending first commit.
- **Next 3 actions:**
  1. First commit; tag `phase-0` after QA evidence lands.
  2. Independent QA (general subagent with the qa-senior role prompt) for F-01..F-03 -> `docs/qa/`.
  3. Send batched human message (batch 1) per docs/04 section 8; then start F-04 (blame + impact).
- **Blockers:** none open.
- **Human pending (batch 1 not yet sent):** GitHub repo + push access; Discord question;
  dogfood runtime choice; optional API keys; Render account later.

---

### 2026-10-15 19:10 IST | Phase P0 | first green suite | STATUS: in progress
- Fixed `Db.module_version()`: FalkorDB returns `MODULE LIST` rows as FLAT key/value lists
  (`['name','graph','ver',42201,...]`), not dicts -> parser now handles both shapes; `db status`
  prints `graph module ver 42201 (OK)` (AT0.1 evidence).
- `map_db_error`: verified raw message `unique constraint violation on node of type Node`
  (v4.22.1) -> mapped to typed `Conflict`.
- Found + fixed a port error in `tests/integration/test_core_scenario.py`: `_build` created
  m1..m6 bare and then again with parents (unique-constraint violation); prototype semantics
  create each node ONCE with parents attached.
- Fixed `revoked_roots(db, gname, trace)` keyword-only mismatch (5 call sites).
- FalkorDB insight: CREATE INDEX for the same label MERGES into one index row
  (Revocation covers root_id+state); schema test asserts property coverage, not row count.
- Confirmed `algo.BFS(r, $depth, 'FEEDS')` accepts `depth=-1` as a parameter (integration green).
- Full suite: 45 passed (unit + integration against real FalkorDB). `make check` green.
- Scripts written: `secret_scan.py`, `check_numbers.py`, `extract_numbers.py`,
  `fetch/start/stop-falkordb.sh` (Linux path, marked [U]), `clean_clone_check.sh`, `seed_demo.py` stub.
- `docs/NUMBERS.md` created (machine block + rules); ruff excludes `docs/` (prototype record).
- Next: commit, QA for F-01..F-03, batched human message, F-04.


---

### 2026-10-15 18:47 IST | Phase P0 | bootstrap | STATUS: in progress
- Environment recon: `python 3.14`/`3.12`/`3.13`, `uv 0.12.22`, `git 2.46.1.windows.1`,
  `docker 29.8.2` (daemon started), `node v24.13.1`, 108 GB free on C:.
- Pack located at the repo working directory; restructured into the layout of docs/02 §3
  (pack docs -> `docs/`, `research/` -> `docs/research/`, `tech/` -> `docs/tech/`,
  `opencode-agents/` -> `.opencode/agents/`, `opencode.json` at root with MCP disabled).
- Decisions ADR-000 (tracks), ADR-001 (Windows + Docker dev host), ADR-002 (Python 3.12),
  ADR-003 (Makefile -> cross-platform Python CLI) recorded in `docs/DECISIONS.md`.
- `docker pull falkordb/falkordb:v4.22.1` OK (digest sha256:b0bdcac2...).
- Next: DB up + MODULE LIST check, F-01 tests.


---

### 2026-10-15 21:39 IST | Phase P1 | F-11 gate, F-10 scenarios, F-09 workspace | STATUS: done (scoped)
- Resumed the original gate import failure; implemented deterministic four-verdict gate,
  static policy classifier, trusted-support checks, bounded evidence paths, REST/MCP and
  stdlib-only Claude hook. Independent reviews found truncation silent-allow and recording
  partial-write defects; fixed with reverify frontier and recording prerequisite checks.
- Commits: 06c82f1 F-11; 38b1376 F-10; 4eb3a66 F-09. Docs/spike reconciliation follows.
- F-10: synthetic S1/S8, private ignored credential, idempotent seeding. QA found unrelated
  fixture-id attestation and support-author overwrite; fixed whole-fixture preflight and
  ON CREATE support author. Main demo seeded healthy; repeated make demo creates nothing.
- F-09: static offline graph workspace, bounded authenticated graph projection, safe text
  sinks, token only in memory, preview/confirm, blame/impact/depth, manual action report,
  real gate form. Actual browser persistence + S8 preservation + medium allow/high reverify;
  native keyboard focus retained; mobile no overflow; screenshots are local/ignored.
- Tests: make check -> 245 passed in31.58s, Ruff PASS, secret scan PASS, numbers PASS.
  Fresh clone+new venv at4eb3a66 -> full pytest245 passed in34.53s and Ruff PASS.
  uv build --wheel -> success; ZIP inspection confirms all required UI assets present.
  F-11 earlier fresh clone ->202 passed; no graph mocks substituted for real FalkorDB.
- QA: docs/qa/F-11.md, F-10.md, F-09.md PASS for declared scope;
  docs/qa/redteam-F-11.md, redteam-F-10.md, redteam-F-09.md PASS with residual limits.
  Builder browser evidence: docs/qa/F-09-browser.md. Independent reviewer operated its own
  read-only browser tab; root's destructive fixture and registry row were removed.
- OpenCode spike: installed1.19.0, free model advertised zero prices; genuine isolated
  plugin/session events captured, provider quota prevented tool execution. F-08 blocked;
  docs/consults/opencode-spike.md and opencode-after-shape.json contain exact limitation.
- Numbers produced: no benchmark CSV. Test timings/counts above are command evidence only.
- Not release-ready: installed capture proof, source identity continuity, authority separation,
  full eval/isolation/ACL/deployment work and human release tasks remain. No push performed.
- Execution policy blocked cleanup of ignored build/browser artifacts; left local/ignored.
  Temporary clean clones remain in OS temp. Current state lists exact next three actions.
---

### 2026-10-16 00:05 IST | Phase P1 | F-07 audit fix + consult 007 capture trust (ADR-008) | STATUS: done
- F-07 capture audit round 2: source-kind fidelity fixed (`source_kind` > `kind` > `web`; kind-only
  events no longer dropped), 10 new adapter unit tests; `docs/qa/F-07.md` PASS.
- Consult 007 (`docs/consults/007-capture-trust/`): domain-researcher + red-team (real FalkorDB
  probes) + senior-architect (role-switch, subagent failed 3x on provider errors; the orchestrator
  wrote it from its own measured probe `scratch/probe_identity.py`). Unanimous direction, ADR-008.
- Shipped (ADR-008): Source identity derived from `(uri, content_hash)` - exact-match indexes +
  composite unique constraint (measured expressible on v4.22.1), one atomic MERGE so repeated reads
  converge and the same uri with a new hash is a new version whose old hash stays revocable; capture
  ids can no longer fork a node or escape revocation; `/v1/events` resolves in-batch aliases.
- Authority is structural: agent tokens record untrusted whatever the body claims (integrity/kind/
  runtime are not credentials), trusted-by-default kinds are rejected without the operator credential,
  MCP `corroborate` accepts only `by="agent"`, REST `corroborate` accepts `human`/`scanner` only with
  a matching `X-Admin-Token`, and `CORROBORATED_BY` is write-once-then-upgrade (an agent edge can be
  upgraded, never downgraded).
- Tests: 281 passed (was 254) - `tests/integration/test_source_identity.py` (7),
  `tests/security/test_capture_trust.py` (14), plus `test_events`/`test_demo_qa` contract updates.
  `make check` green (ruff + pytest + secret scan `--history` + numbers).
- KNOWN_ISSUES 11/12 closed for the shipped surface; new residuals 16/17 documented.
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); FalkorDB v4.22.1 (Docker,
  pinned); Node v24.13.1.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST.
- **Next 3 actions:**
  1. F-14 spec + E1/E2 independent oracle + baselines + NUMBERS pipeline (`make eval`).
  2. F-15 isolation/concurrency (ACL users, hypothesis + threads, invariants) and F-16 deploy path.
  3. F-23 README/blog/video/submission pack once the numbers exist.

---

### 2026-10-16 00:15 IST | Phase P2 | F-14 E1 (contamination semantics) | STATUS: done (E2/E3 next)
- Built `evals/`: `gen.py` (seeded DAG generator: S sources, M memories in L levels, fan-in f,
  p_corr independent corroboration, A actions 20% irreversible, parent-inheriting synthetic text),
  `oracle.py` (**independent** brute-force fixpoint ground truth), `baselines.py` (B0 TF-IDF cosine
  with theta calibrated on disjoint seeds, B1 first-provenance, B2 flat 1-hop, B4 full cascade,
  B5 time-travel rewind, P = the engine's real `compute_final`), `stats.py` (Wilson + 10k bootstrap),
  `machineinfo.py`, `run_e1.py`, `run_all.py`.
- Headline (18 cells x 30 seeds, 6 systems, `evals/REPORT.md`): P recall **1.0**, over-invalidation
  **0.0**, preserved_correct **1.0**; B4 over-invalidation rises to **0.278** at depth 6 / fan-in 3;
  B2 recall falls to **0.186** pooled (0.24 at depth 6); B5 over-invalidation **0.956**; B1 recall
  **0.355**; B0 recall **0.554** with theta **0.475** calibrated on 24 disjoint seeds. All values
  with 95% CIs in `docs/NUMBERS.md` (regenerated by `make eval`).
- Correctness proof: 1000 random small DAGs agree exactly between the oracle and
  `engine/compute.py`; the in-process P path is cross-checked against a **real FalkorDB revoke** on
  three generated shapes (`tests/evals/test_oracle_agreement.py`).
- 292 passed, ruff PASS, secret scan PASS, `make eval` 63 s, `make eval-quick` 4 s.
- **Next 3 actions:**
  1. E2 capture-fidelity model (edge-drop d in {0,1,2,5,10}%, read window K in {5,10,25,50,100}).
  2. F-15 isolation/concurrency (per-tenant ACL users, hypothesis + threads, invariants).
  3. F-16 deploy path (Dockerfile single container, local run, `/readyz`, seed on boot).

---

### 2026-10-16 00:35 IST | Phase P2 | F-14 E2 (capture fidelity) | STATUS: done (E3/E4/E5/E6 next)
- `evals/run_e2.py` + report section + numbers keys: precise capture with d in {1,2,5,10}%
  of DERIVED_FROM edges dropped (one draw stream per seed so a higher rate drops a superset -
  the naive independent-per-rate version produced a non-monotone, unexplainable sweep) and the
  conservative read window with K in {5,10,25,50,100} carried reads per modelled session
  (5 actions per bucket, which is why the K sweep saturates around 25 - reported as-is).
- Measured (30 seeds, `evals/results/e2_capture.csv`): exact leak 0.0; edge drops leak
  **0.011 / 0.037 / 0.153 / 0.261** at 1/2/5/10%; the window never leaks but over-flags by
  **5.0x-6.3x** and flags ~3.4x the truly-affected actions. Model stated plainly in REPORT.md.
- `make eval` 71 s, `make eval-quick` 4 s; 292 tests green; ruff, secret scan, check_numbers PASS.
- 35 numbers in `docs/NUMBERS.md`, all with 95% CIs, all generated by committed scripts.

---

### 2026-10-16 00:55 IST | Phase P2 | F-15 isolation/concurrency + two identity fixes | STATUS: done (ACL wiring open)
- `tests/integration/test_isolation_concurrency.py`: (1) API isolation matrix - tenant B gets
  404 for A's blame/impact/revoke/corroborate and `reverify` (never "safe") from the gate for
  A's ids, with A's graph provably untouched; (2) 20 tenants x 8 writer threads -> every graph
  passes `check_invariants`, holds exactly the nodes its 8 writers produced, and has zero
  foreign-tenant nodes; (3) revoke racing two ingest writers leaves a consistent graph.
- `tests/security/test_acl_mechanism.py`: real ACL users scoped to `~ped:<tenant>` and
  `~ped:<tenant>:wi:*` can work in their namespace and are denied every other graph, including
  `GRAPH.COPY` into a foreign namespace (pack 13_acl pattern, verified on v4.22.1; skipped
  without `PEDIGREE_DB_ACL_SECRET`, which is deployment config and never committed).
- **Two real defects found and fixed while making the stress test honest:**
  1. `Db` held ONE FalkorDB connection for all threads - 160 concurrent writers turned load into
     `unavailable` timeouts. Connections are now per-thread (measured before/after in the report).
  2. Source identity raced: 8 concurrent writers of the same uri produced 7 nodes. Root cause: a
     MERGE keyed on `(tenant, uri)` with a NULL `content_hash` is NOT protected by the
     `(uri, content_hash)` constraint (NULLs are exempt), so hash-less captures now derive a
     stable id (`sha256(tenant|uri)`) and MERGE on the Node(id) constraint instead, and the
     hashed path reads back on a conflict instead of surfacing an error.
- 295 tests pass; ruff PASS.
- KNOWN_ISSUES 18/19/20: ACL users verified-but-not-wired (service isolation is API-level),
  per-thread connection count, and engine writes assuming the per-tenant schema.

---

### 2026-10-16 01:10 IST | Phase P2 | F-16 deployment path (Docker, verified) | STATUS: done locally; Render is a human step
- `Dockerfile` (Ubuntu 24.04, Python 3.12, pinned FalkorDB module fetched at build time and
  asserted executable, `healthcheck` on `/readyz`), `scripts/entrypoint.sh` (module check ->
  FalkorDB with the mandatory args -> wait for readiness -> optional demo seed -> uvicorn),
  `docker-compose.yml`, `.dockerignore`.
- **Verified on this machine**: `docker build` OK; container boots FalkorDB 4.22.1
  (`pedigree cli db status` inside: module ver 42201 OK), seeds the demo tenant
  (`{"created": 11, "existing": 0, "invariants": "pass", "scenarios": ["S1","S8"]}`), and serves
  `/healthz`, `/readyz`, `/`, `/docs`, `/metrics`, `/v1/graph`, `/v1/stats`, `/v1/gate` (200;
  a high-risk push relying on a captured source returns `reverify` + `untrusted_influence`), and the
  demo revoke loop: dry-run `would_taint 5` with the affected actions, then the real revoke
  `state done, tainted 5`, graph `{"ok":5,"revoked":1,"tainted":5}`.
- KNOWN_ISSUES 4 (Linux scripts never executed) is now closed: the same scripts ran inside the
  image. Render remains a human step (no account yet) - documented in README "Deploy".
- 295 tests pass; ruff PASS.

---

### 2026-10-16 02:05 IST | Phase P4 | F-23 docs pass (README, WALKTHROUGH, blog, submission, demo script) | STATUS: mostly done
- README rewritten to the hackathon requirements: pitch, why-a-graph, quick start, graph data
  model, **every Cypher/algorithm the product depends on** with purpose, REST/MCP/hook/plugin
  install, security model, evaluation summary (NUMBERS.md only), honest limitations, deploy,
  tracks, status table.
- `docs/WALKTHROUGH.md`: every query and decision explained simply with runnable commands -
  verified against the live service (blame path, invariants clean, gate reverify on a high-risk
  push relying on a captured source).
- `docs/BLOG-DRAFT.md` (blog side prize), `docs/submission/SUBMISSION.md` (ready-to-paste),
  `demo/script.md` + shot list, `AI_DISCLOSURE.md` updated for this continuation.
- Two defects found by *running the documented quick start*: `make demo` died on a stale local
  credential file (fixed + regression tests; an unreadable file is still refused), and
  `make eval-quick` overwrote the published `docs/NUMBERS.md` block with quick-cell values
  (fixed: the quick run writes `numbers_quick.json`; static facts now come from
  `evals/static_numbers.py` so a full `make eval` never drops `falkordb_version`/`python_min`/
  `tracks_entered` again).
- 296 tests pass; ruff, secret scan and `check_numbers` (README + blog + submission +
  WALKTHROUGH) all PASS.

---

### 2026-10-16 03:00 IST | Phase P2/P4 | F-14 E3/E4 + QA reports for F-13/F-15/F-16 | STATUS: done
- `evals/run_e3.py` + `tests/evals/test_e3_scenarios.py`: every authored scenario replayed through
  the HTTP API (`/v1/events` per node, operator-credential attestation, `/v1/revoke`), asserting the
  fixture's expected statuses plus gate probes (high-risk push on the revoked branch is never
  `allow`; an unknown id is `reverify`). Found and fixed while writing it: actions link to their
  session, so the replay now starts with `ensure_session` (without it the API correctly refuses).
- `evals/run_e4.py`: latency for revoke/blame/impact/gate at 820/2460/8200 nodes through the real
  engine (the real revoke is timed on a different root per round - a repeat revoke is idempotent by
  design). The README points at the regenerated CSV instead of quoting drifting numbers.
- QA reports written from real runs: `docs/qa/F-13.md`, `F-15.md`, `F-16.md` (each states its
  residual rather than softening it).
- `make eval` 80 s end-to-end (E1 -> E2 -> E4 -> E3 -> numbers -> NUMBERS.md -> REPORT.md ->
  check_numbers); 300 tests pass; ruff/secret/numbers PASS.

---

### 2026-10-16 03:25 IST | Phase P2 | F-12 confidentiality + S6 | STATUS: done
- `demo/scenarios/S6.json`: HR source -> summary memory -> public README write, with four
  `expected_gate` steps (public blocked, default audience blocked, tag audience allowed, superset
  allowed).
- `tests/integration/test_confidentiality.py`: tag inheritance, transitive inheritance, the
  audience boundary (a partial superset is still blocked - the missing tag is what blocks), and the
  hook `deny` mapping. `docs/qa/F-12.md`.
- E3 now revokes a root only when the fixture declares `expected_after_revoke`; a gate scenario
  (S6) is replayed with its lineage intact, and every `expected_gate` step is asserted through
  `/v1/gate` (`tests/evals/test_e3_scenarios.py::test_scenario_gate_expectations_hold`).
- Two fixture-level bugs fixed while doing it: the seeder's preflight compared `conf` against an
  empty list (a fixture that declares a tag collided with itself on re-seed), and a test asserted
  the old node count for the demo seed.
- 307 passed, 1 skipped; ruff PASS; `make eval` green; demo tenant re-seeded with S1/S6/S8.

---

### 2026-10-16 04:10 IST | Phase P3 | F-17 what-if (GRAPH.COPY) | STATUS: done
- `src/pedigree/engine/whatif.py`: `GRAPH.COPY` of the tenant graph (indexes kept), the **real**
  revoke engine on the copy for each root, a status diff against the original, the affected and
  irreversible actions, then the copy deleted in a `finally` - a what-if can never leave the real
  lineage changed. Per-tenant concurrency capped, and copies this process does not track (crash
  leftovers) are reaped on the next call.
- REST `POST /v1/whatif` + MCP `pedigree_whatif`; `tests/integration/test_whatif.py` (5):
  the diff matches what a real revoke produces (same engine, same graph shape), the real graph is
  byte-identical afterwards, stale copies are reaped, empty/oversized root lists are rejected, and
  both interfaces return the same counts.
- 312 passed, 1 skipped; ruff PASS.
