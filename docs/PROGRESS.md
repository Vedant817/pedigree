# CURRENT STATE (overwritten after every feature / checkpoint)

- **Phase:** Phase C security hardening, Fri 2026-10-16 21:17 IST. P-029 hygiene and
  P-014 request-wide quota admission have independent QA/red-team PASS. Current full
  `make check`: 582 passed, 1 skipped, 3 deselected, 1 xfailed; Ruff, tracked secrets
  and numbers PASS. P-014 committed in 303016a, P-029 test follow-up f940b23.
  P-015 consult 010 / ADR-011, implementation, independent QA/red-team and full gate
  PASS. Dogfood now 20 PASS, 3 expected failures, zero leftovers. P-021 consult 011
  complete; decision/implementation next. No Phase-C checkpoint or push yet.
- **Last implementation commits:** 1243744/031f86a/83d7b73 (P-016 QA follow-up: stdio default-tenant
  token bypass fixed - red-team F-1 with red-at-parent regression; MCP errors actionable; README
  auth reality + 13-tool list; QA addenda), ef9033f (P-012 consult trio filed: domain + oracle
  review + architect), 0e36767 (dogfood harness + `make dogfood`), 0e27023 (P-025 spec),
  a2cb57b (P-013 spec), 44cf5bf (P-011 spec), 561b7e2 (P-016 fix + acceptance tests, QA-closed),
  32ebaeb (P-010 anchor-lint closure rounds; QA-closed),
  ccdd7cb (P-010 :Node(id) anchor fix, audit-fix program Phase A),
  bb9511a (F-08 review fixes incl. round-2 closure, amended
  in place), 8dd6509 (F-08 OpenCode read-only slice incl. review hardening),
  f475979 (OpenCode ADR-009 record), a677d9f (what-if/audit containment), d7f7409 (test fixture
  ownership).
- **Environment:** Windows 11; Python 3.12.15; pinned FalkorDB module 42201 in Docker;
  Node v24.13.1. Local core and synthetic demo require no model provider.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; target submit 21:00; hard stop 23:59.
- **Previous checkpoint test state (not a current full-suite rerun):** make check: 406 passed, 1 skipped (optional ACL deployment secret absent),
  3 deselected (perf; `make check-perf` 3 passed - EXPLAIN index plans, 20 000-node revoke
  1 376 ms, 60 020-node gate 4.0 ms; P-010 QA re-measured 1 371.9 ms / 2.1-4.3 ms on its own
  harness), 1 xfailed (strict read-window watchdog), Ruff, tracked secret scan and numbers
  check PASS; `scripts/check_secrets.sh` PASS including git history.
  **P-016 QA-closed:** acceptance trio green (stdio journey, `/mcp` mount, advertised
  `http://127.0.0.1:8000/mcp` URL); qa-senior PASS (`docs/qa/P-016.md`, 20 adversarial cases,
  zero graph leaks) plus devex (`docs/qa/devex-P-016.md`) and red-team
  (`docs/qa/redteam-P-016.md`) reports; red-team F-1 (stdio ignored `PEDIGREE_MCP_TOKEN`) fixed
  (`83d7b73`) with red-at-parent regression `tests/security/test_p016_stdio_token.py`;
  F-2/F-3/F-5 -> P-015 scope, F-4 -> P-021.
  **Dogfood harness live:** `make dogfood` (21 heavy-user scenarios + P-id expectation table):
  PASS=12 FAIL=0 EXPECTED-FAIL=9 STALE=0 SKIP=1, exit 0; `--strict` exits 1 by design; S19
  1 500-node revoke 156 ms server-side, invariants clean.
  F-08 slice: builtin Node suite 38 passed; hook-replay integration (live API + real FalkorDB)
  3 passed; security regressions 1 passed + 1 strict xfail; round-3 independent re-confirmation
  PASS. Independent what-if/audit QA: 45 passed; test-fixture ownership QA: 11 passed. Full
  serialized evaluation PASS; independent scoped F-14 statistical signoff PASS.
- **Verified scope:** F-01..F-07, F-09..F-12, F-16 local container, F-17 what-if subset,
  F-18 PageRank/exact reach. Checkpoint/restore and WCC remain unbuilt.
  F-13/F-15 service ACL wiring remains open. E1/E2 synthetic semantics/capture model,
  E3 authored S1/S6/S8, E4/E4b local measurements are distinct from real-session evidence.
- **Capture:** OpenCode adapter implemented as an explicitly enabled read-only slice (ADR-009,
  `adapters/opencode/`): native reads gated and captured as observed read views, every other tool
  denied, failed capture latches the session. Review round hardened Windows path handling
  (alternate-stream/drive-relative denial, native case canonicalization) and disclosed the bounded
  latch memory, read-window and TOCTOU limits (adapter README). Its tests replay the genuine 1.19.0
  payload; installed acceptance of the plugin file, write shapes and real coverage remain unmeasured.
  Claude hook has API/subprocess proof, not installed-runtime proof.
- **Data safety correction:** the old isolation fixture deleted all registry tenants. It now
  deletes only its own successful creates and reports cleanup failures. Independent real-DB
  sentinel survival passes. Earlier runs cannot establish that pre-existing data was preserved.
- **Next 3 actions:**
  1. Fresh-clone role verification, P-021 consult decision/ADR and test-first implementation.
  2. Independent P-021 validation/body-limit/error QA and red-team; flip S08/S09 only on proof.
  3. P-021 validation/error containment and P-020 auth/rate limits; Phase-C checkpoint only
     after independent security reports and clean-clone verification.
- **Human pending:** video recording, walkthrough/architecture review, organizer track decision,
  hosted account/submission. Git origin is configured; this continuation has not pushed.

---

### 2026-10-16 ~18:00 IST | Phase B checkpoint | P-011 + P-012 + P-024 + P-031 committed | STATUS: done
- Brief close entry: Phase B code + tests committed with `make check` + `make dogfood` green; QA trio for P-013/P-025 delivered `docs/qa/P-013.md` (PASS) + red-team + devex reports (see those). Next: checkpoint B push + Phase C consult (P-015).

### 2026-10-16 17:18 IST | Phase B | P-011 + P-012 closed | STATUS: done
- **P-011 (recoverable revokes) closed.** `revoke()` now finishes a `running` Revocation instead of
  no-op; `resume_incomplete` runs in a bounded daemon thread at startup; `/v1/admin/resume`
  (admin-gated) + `pedigree resume [--tenant]` exposed; `Db._run` treats empty-graph "empty key"
  as zero rows (robustness). 9 new integration tests (fault injection, kill-process, barrier/fixpoint,
  startup wiring, admin resume, CLI) + regression guards; invariant check now silent where crash
  recovery leaves no quarantined. `make check` 422 → (still PASS) after this work.
- **P-012 (`reinstate` correctness) closed.** Shared `resolve(db, gname, roots, seeds=…)` with the
  cleaned "re-resolve remaining, never clobber a revoked root"; Q_REINSTATE_RESET (the blanket
  reset bug) deleted; CAS root flip + supersede step + `remaining_roots` keys unchanged for tests.
  Adds the node-level invariant `revoked_at IS NOT NULL AND status <> 'revoked'` (catches the
  clobbered shape), proven on repro (cwitched root s_web scales; invariants empty); repro test
  `tests/integration/test_reinstate_independent_root.py`: A→B→Cc, revoke A, revoke B, reinstate A
  -> A=ok, B=revoked, Cc=tainted. Invariant fires on synthetic clobbered node (verified).
- **P-012 consults filed** (`docs/consults/008-p012-reinstate/`): domain (cost + stale-metadata
  facts), oracle review verdict "NOT YET" with concrete corrections, architect `rederive(roots,
  seeds)` recommendation. 300-example hypothesis battery + task-oracle mapping deferred to E1's
  `evals/oracle.py` / `evals/test_oracle_agreement.py` (existing independent oracle), with the
  runnable driver seeds supplied.
- **Phase C specs drafted (first pass):** P-014, P-015 (consult mandatory before impl), P-020,
  P-021 (F-4 chunked body + exception-leak closure), P-029, P-036 in `docs/fixes/`.
- **Gate:** make check PASS; new P-011 + P-012 test suites green (9 + 2).
- **Next:** Phase B remaining: P-024 (reconcile stragglers) + P-031 (parent restriction), then
  checkpoint B. QA agent (P-013/P-025) outcomes still open due to provider rate limits —
  see `docs/qa/P-013.md` (skeleton), `docs/qa/P-025.md` (skeleton), `redteam-P-013.md`
  (partial). P-012 to get the QA trio at Phase C kickoff.

### 2026-10-16 16:32 IST | FIX_PROMPT Phase A | P-016 closed (QA trio + F-1 fix), dogfood harness, Phase B prep | STATUS: done
- **P-016 QA-closed.** Acceptance trio (stdio CLI journey, `/mcp` mount, advertised URL) green on
  frozen `561b7e2`; qa-senior PASS (red-at-parent reproduced: `Settings.try_query` AttributeError +
  `POST /mcp` 405; 20 adversarial cases typed/safe; zero graph leaks) plus devex and red-team
  reports filed (`docs/qa/P-016.md`, `devex-P-016.md`, `redteam-P-016.md`).
  Red-team **F-1 (High)**: stdio `_resolve` never checked `default_tenant_token` - the tenant id
  alone authorized tokenless calls (incl. revoke/reinstate) and a wrong env token silently worked.
  Fixed in `83d7b73` (env pair must resolve together) with red-at-parent regression
  (`tests/security/test_p016_stdio_token.py`); `unauthorized` MCP errors now carry actionable
  messages (were `null`); `pedigree_check_action` unauthorized/quota messages added.
  F-2/F-3/F-5 -> P-015 scope, F-4 -> P-021 (recorded in the reports).
- **Docs reality pass:** README MCP section (auth reality until P-015; full 13-tool list),
  `make demo` wording matches the seed (path printed, token inside the file), dead stdio command in
  `docs/09-TECH-CHEATSHEET.md` fixed, FEATURES F-06 `/mcp` routing note added, QA addenda written.
- **Dogfood harness landed** (`0e36767`, `make dogfood` / `dogfood-strict`): 21 heavy-user
  scenarios with a P-id expectation table; first runs found 3 harness bugs (fixed), then
  PASS=12 FAIL=0 EXPECTED-FAIL=9 STALE=0 SKIP=1, exit 0; `--strict` exits 1 by design. S19:
  1 500-node revoke 156 ms server-side, `check_invariants` clean.
- **Phase B prep:** P-011/P-024/P-031 specs committed; P-012 mandatory consult trio filed
  (`docs/consults/008-p012-reinstate/`): domain facts (blanket reset wipes root status before
  `revoked_roots()` is read; stale `revoked_at`/`reason` left on un-revoked nodes; 20k cost
  numbers), oracle review verdict **NOT YET** (pin corrected semantics into the oracle; lazy
  corroboration; concrete invariant `revoked_at IS NOT NULL AND status<>'revoked'` == 0) and
  architect recommendation (one `rederive(roots, seeds)` helper for revoke/reinstate/resume/
  reconcile; delete `Q_REINSTATE_RESET` as the bug itself).
- **Gate:** `make check` 406 passed, 1 skipped, 3 deselected, 1 xfailed; secret scan + numbers
  PASS. **Next:** P-013 red tests -> fix, then P-025, then the Phase A push checkpoint.

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

---

### 2026-10-16 04:25 IST | Phase P3 | F-18 audit_sources (PageRank + exact reach) | STATUS: done
- `src/pedigree/engine/audit.py` + `GET /v1/audit/sources` + MCP `pedigree_audit_sources`:
  `algo.pageRank` over `Node`/`DERIVED_FROM` for the ranking, and the exact descendant count from
  `algo.BFS` (which excludes the start node - verified by probe) next to each score, so the two are
  never conflated. `tests/integration/test_audit.py` (4) covers both counts, the limit clamp, REST
  and MCP.
- 316 passed, 1 skipped; ruff, secret scan, numbers PASS.

---

### 2026-10-16 08:57 IST | P2/P3 | containment, fixture ownership, coherent evaluation | STATUS: verified locally
- a677d9f: truthful what-if cleanup, pending-capacity accounting, lease-aware reaping, typed
  copy errors, baseline from the same atomic snapshot, five-root validation; isolated audit
  sources retain exact zero reach and null PageRank when the procedure emits no score.
  Independent QA/red-team: 45 passed; cap is per process, checkpoint/restore and WCC unbuilt.
- d7f7409: repaired destructive all-tenant test teardown. Only fixture-owned successful creates
  are cleaned; remaining/unknown graphs and registry errors are reported after other cleanup.
  Independent QA: 11 passed including a real pre-existing tenant sentinel. Earlier runs may
  have removed pre-existing data; only the dedicated synthetic demo was re-seeded (14 nodes,
  S1/S6/S8, invariant PASS). No recovery of arbitrary data is claimed.
- 3941d85: whole-DAG seed-cluster bootstrap, valid/total cluster and item denominators, retained
  CSV intervals and E2 seed samples, consistent B0 calibration universe, exact E4b ID sets,
  quick-output isolation. Full serialized evals/run_all.py PASS against this committed source.
  Report/CSV/JSON/NUMBERS coherent; independent F-14 signoff PASS for stated synthetic/local
  scope. SQLite faster on measured traversal rows; no graph-engine superiority claimed.
- make check: 391 passed, 1 skipped (ACL deployment secret absent), Ruff/secrets/numbers PASS.
  Expanded numbers check: README/blog/submission/walkthrough PASS against 68 allowed values.
- 3beaae1: genuine free OpenCode before/after read payload recorded; one tool completed with
  reported cost zero, final model response timed out at 60 seconds and own process tree stopped.
  Observation resolves the read-shape prerequisite only; adapter and real coverage/friction
  remain unbuilt/unmeasured. Documentation no longer claims the adapter ships.
- Remaining gates: OpenCode adapter/runtime acceptance, service ACL wiring, E3b/E6, durable
  hook spool/replay, human walkthrough/video/submission. Fresh-clone verification of a020851 PASS: new Python 3.12.15 venv, 56 resolved packages,
  make check 376 passed / 1 skipped in 39.45s, Ruff/secrets/numbers PASS. CORRECTION: post-clone demo lookup failed (tenant not found); a second destructive
  E3 fixture was then discovered. The prior demo-preservation sentence was written before
  checking command exit status and was unsupported. E3 fixture repair/verification is pending. This is Windows/local DB evidence,
  not a new hosted deployment or installed runtime acceptance.


### 2026-10-16 09:09 IST | P2/P3 | E3 cleanup correction and suite preservation | STATUS: verified locally
- 72c7650: removed a second all-tenant cleanup loop from the E3 boundary fixture; the fixture
  now owns only its TestClient. Individual scenarios and run() clean their exact random IDs.
  Header construction moved inside run()'s cleanup boundary; deterministic test tenant names
  replaced by UUIDs. New independent E3 QA: 21 targeted cases passed, no xfails.
- A lazy session DB sentinel now detects unrelated graph/registry deletion anywhere in a
  DB-using suite. Independent negative test deliberately deletes only its own nested sentinel
  and proves detection; unit-only checks remain DB-free. Broad search/static fixture guard
  found no remaining all-registry deletion fixture. Ownership is tested, not inferred from
  a passing suite count. Cleanup DB-error paths are still explicitly limited in the QA report.
- Root make check: 391 passed, 1 skipped in 34.73s; fresh local clone of 72c7650 in a separate
  new venv: 391 passed, 1 skipped in 38.86s. Ruff, tracked secret scan, numbers PASS. After
  each suite a separate command confirmed demo registry retained and 14 synthetic nodes.
  This supersedes the earlier unsupported preservation claim; historical data recovery is not claimed.
- Automatic approval review rejected recursive removal of the two task-owned temporary QA
  clones as blocked by policy. They remain under the OS Temp directory (pedigree-final-9dab960007b84184888631fbaf435cbf
  and pedigree-verified-ca56abfe591f408ba95e5fc57b7c8d7e); no alternate deletion attempted.


### 2026-10-16 09:42 IST | Phase P2/P3 | F-08 opt-in OpenCode read-only capture slice | STATUS: implemented; independent QA/red-team pending
- `adapters/opencode/` (dependency-free Node ESM; entry `pedigree.js`, core `pedigree-core.js`,
  install/config/limits in its README) implements ADR-009: disabled without
  `PEDIGREE_OPENCODE_ENABLED=1`; only the observed native `read` tool is accepted and every other
  tool is denied before execution; reads are path/credential/symlink-validated, gated through
  `/v1/gate` (block/reverify/unknown/outage deny; an outage does not latch), and completed reads
  capture session + observed read view (`readview:v1/<project-key>/<rel>#L<range>` + canonical
  display-descriptor digest, no file bytes/outputs/commands/absolute paths/token on the wire) +
  session_read edge via `/v1/events`. Failed/ambiguous capture latches the session incomplete and
  denies further operations; per-session gate/capture serialization; bounded sessions/pending/
  acked memories; no redirects, HTTPS except loopback, timeouts and response caps.
- Evidence: builtin Node suite 35 tests (genuine-fixture wire mapping, gate/denial matrix,
  containment and display-validation matrix, privacy canaries incl. a body-key allowlist,
  bounds/clamps/eviction/URI overflow), run under pytest by
  `tests/unit/test_opencode_adapter_suite.py`; `tests/integration/test_opencode_plugin.py`
  replays the genuine 1.19.0 payload through a Node subprocess into a live API + real FalkorDB:
  persisted Source with independently recomputed digest and forced `untrusted` integrity, Session
  runtime + read window, revoke -> `reverify` denial with nothing captured, and identical captures
  isolated per tenant. Labelled hook replay, not installed OpenCode execution.
- Adjustments from reading the current runtime docs and the genuine recheck: install path is
  `.opencode/plugins/` (plural) and the entry exports a single named plugin function (default
  export dropped to avoid double registration).
- Scope honesty: F-08 remains implementing; installed acceptance of this plugin file, write/edit/
  shell shapes (provider-blocked) and real coverage remain unverified.
- make check: 394 passed, 1 skipped in 42.37s; Ruff, tracked secret scan, numbers PASS.


### 2026-10-16 10:31 IST | Phase P2/P3 | F-08 review round: QA round-1 + red-team findings fixed/disclosed | STATUS: fixes landed; independent round-2 re-verification in flight
- QA round 1 (`docs/qa/F-08.md`) verdict FAIL: `make check` red on this slice's own privacy canary
  matching the tracked secret scanner (F08-QA-1, High), stale root README "adapter unbuilt" lines
  (F08-QA-2), "byte-for-byte" wording (F08-QA-3). Red-team round (`docs/qa/redteam-F-08.md`,
  evidence `scratch/redteam-f08/`) found a High Windows ADS credential bypass (`id_rsa::$DATA`
  etc.), a Medium drive-relative `C:file` wrong-file provenance, a Medium case-split Source
  identity (non-native realpath), three disclosure-level limits (latch-ring forgetting, gate
  read-window eviction, TOCTOU swap), and pre-existing P-014 (out of scope, `AUDIT.md`).
- Fixes: win32 path-grammar denial (`path_stream`) for alternate-stream/drive-relative forms;
  native realpath for root and resolution (case-convergent identity); canary assembled at runtime
  and the unpushed commit rewritten (`c14d7fb` -> `8dd6509`) so no credential-shaped literal exists
  in history; stale docs across README/FEATURES/KNOWN_ISSUES/BLOG-DRAFT corrected; disclosures
  added to the adapter README known limits.
- New permanent coverage: `tests/security/test_security_F08.py` (stream/drive-relative denial with
  a silent listener proving zero connections; strict-xfail read-window eviction watchdog); win32
  regressions in `paths.test.js`; case-convergence live integration test.
- Evidence: `make check` 396 passed, 1 skipped, 1 xfailed; Ruff/secret/numbers PASS;
  `scripts/check_secrets.sh` PASS including history; Node suite 37 passed; security 1 passed + 1
  strict xfail (`--runxfail` shows exactly the recorded eviction semantics); integration 3 passed
  on live API + FalkorDB 42201; red-team live re-run shows case variants converging on one Source
  (pre-fix: two).
- Honesty: F-08 remains implementing; hook-replay only; the three disclosures are limits, not
  guarantees changed.


### 2026-10-16 11:00 IST | Phase P2/P3 | F-08 review cycle closed: round-2 FAIL fixed, round-3 PASS | STATUS: independent re-confirmation PASS at `bb9511a`; F-08 remains implementing
- Round-2 verdict (independent QA, `docs/qa/F-08.md`): FAIL on one artifact - the review-evidence
  commit itself (`a2b7fc4`) reintroduced the canary literal in its own report (F08R2-QA-1, High:
  `make check` exit 2, `check_secrets.sh` exit 1 including history), plus a Low fail-closed
  over-denial for in-project names starting `..` (F08R2-QA-2) and an Info `\\?\` over-denial
  accepted as fail-closed (F08R2-QA-3). All code/test suites were green in round 2.
- Fixes at the amended commit `bb9511a` (was `a2b7fc4`; unpushed before and after): the canary
  assignment is paraphrased and two verbatim command arguments in the report are redacted;
  `resolveWithinRoot` uses a segment-aware escape test (`escapesRoot`) in both branches with a
  `..x`/`..foo/y.txt` allowed-vs-traversal-denied regression (Node suite 37 -> 38). Re-running the
  reviewer's own probe: exactly rows 21/22 changed to allow+captured.
- Evidence: `make check` 396 passed / 1 skipped / 1 xfailed; Ruff/secret/numbers PASS;
  `scripts/check_secrets.sh` PASS including git history; `git log -S` and `git grep` clean for the
  canary literal and its prefix; Node 38/38; security 1 passed + 1 strict xfail; integration
  3 passed; round-3 independent re-confirmation PASS (fresh gate reruns + full 58-row probe diff:
  only the two over-deny rows changed, every denial row byte-identical with fetches 0).
- Honesty: F-08 remains implementing; hook-replay only, installed-runtime acceptance unclaimed;
  F08R2-QA-3 stays accepted fail-closed; the amended-away commits remain as dangling local,
  unreachable objects until a future `git gc` (not scanned by the history scan, not pushable).


### 2026-10-16 12:45 IST | Phase A (FIX_PROMPT) | P-010: every id anchor on the unique :Node(id) index | STATUS: landed `ccdd7cb`; independent QA in flight
- All eleven `MATCH (x:<TypeLabel> {id:...})` anchors rewritten to
  `MATCH (x:Node {id:...}) WHERE x:<Label>` in `src/pedigree/db/queries.py` (corroborate,
  session/read-window, revoke support/actions/artifacts/revocation-state, demo support, gate
  support). EXPLAIN changes from `Node By Label Scan` to `Node By Index Scan` (probe:
  `scratch/p010_recon_explain3.py`; all 11 index=True/labelscan=False).
- Tests first: `tests/unit/test_query_lint.py` RED with exactly the 11 offenders, then green;
  `tests/perf/test_revoke_scaling.py` (marker `perf`): plan assertions plus 20 000-node revoke
  < 20 s and `check_action` with 10 relied-on ids on 60 020 nodes < 100 ms. New `make check-perf`;
  `test-quick` now deselects `perf`.
- Measured on pinned FalkorDB 42201: 20 000-node chain revoke 1 376 ms (19 999 tainted,
  `check_invariants` clean); gate 4.0 ms, decision allow. The A1 target (10 000-node revoke
  < 10 s) is met at 2x size.
- Evidence: `make check` 397 passed / 1 skipped / 3 deselected / 1 xfailed; Ruff, tracked secret
  scan, numbers check PASS; `make check-perf` 3 passed.
- Honesty: query-shape/latency change only, no API or semantic change claimed; the four rewritten
  write queries (`Q_CORROBORATE`, `Q_SESSION_READ`, `Q_REVOCATION_SET_STATE`, `Q_DEMO_ADD_SUPPORT`)
  are covered by the existing suite plus plan assertions, not by new behaviour tests. QA re-runs
  EXPLAIN over every query in `queries.py` and lands `docs/qa/P-010.md`.


### 2026-10-16 13:35 IST | Phase A (FIX_PROMPT) | P-010 QA closure: PASS at declared lint scope | STATUS: closed; next Phase A items P-013/P-016/P-025
- Independent QA (`docs/qa/P-010.md`, rounds at `09f0f7b` -> `32ebaeb`): fresh `make check`
  399 passed / 1 skipped / 3 deselected / 1 xfailed, `make check-perf` 3 passed, `make test`
  400 passed, `scripts/check_secrets.sh` PASS. Own EXPLAIN census of all 84 query constants
  (11 rewritten anchors index-backed; counterfactual without `ensure_schema` shows label scans).
  Own perf harness: 10k chain revoke 658 ms, 20k 1 372 ms, ternary-tree 9 841 nodes 539 ms,
  gate 2.1-4.3 ms; pre-fix 10k revoke 17 841 ms reproduces the audit. 15/15 semantic equivalence
  checks and demo seeding identical; no overclaims found. Builder's numbers confirmed.
- Three follow-up rounds closed P010-QA-1 (lint evadable by formatting/grammar variants):
  `4e070a8` (whitespace/case tolerance), `88ba332` (anonymous variable + WHERE form),
  `32ebaeb` (parenthesised predicate + relationship in the leading pattern list). Lint scope
  declared final in the module comment with a documented accepted-residual list (deliberate
  paraphrase only; none present in `src/`). Round 4: CLOSED at declared scope, safe battery
  0 true false positives, pre-fix sensitivity 11/11.
- New finding P010-QA-2 (Info, pre-existing, out of P-010 scope): `tests/integration/test_mcp.py`
  and `tests/security/test_security_F06.py` leak `ped:mcp*` graphs (34 in the local DB). Queued
  with test hygiene; no code or latency impact.


### 2026-10-16 18:08 IST | Phase C | P-029 independent hygiene follow-up | STATUS: done
- 5bed8a4: removed duplicate Pydantic timeout validator; production /docs, /redoc and
  /openapi.json now follow one visibility setting; non-ASCII metrics-token bytes reject
  with 401 rather than raising a comparison exception/500. No role-separation claim.
- Independent red: 3 failed / 20 passed; metrics malformed bytes500, ReDoc200 and
  OpenAPI200 reproduced. Parent configuration warning reproduced with warnings-as-errors.
- Independent final command: .venv/Scripts/python.exe -m pytest
  tests/security/test_p029_hygiene.py tests/unit/test_timeout_settings.py -q -s --tb=short
  -> 35 passed in6.04s; session ownership sentinel PASS. Ruff PASS; secret_scan --history
  PASS. Reports docs/qa/P-029.md and redteam-P-029.md include actual red/green evidence.
- P-014 consult found unlocked count/create unsafe even inside one Falkor query: cap1
  admitted4 under independent connections. Write-first barrier fixed that narrow probe,
  not a multi-query batch. Decision009 uses explicit public admission and a nonexpiring
  owner-token mutex, bounded wait, identity-aware preflight and fail-closed stranded locks;
  stable primary/no-eviction assumptions and manual quiescent recovery remain explicit.
  Implementation/independent quota review pending; no current full-suite green claimed.

### 2026-10-16 21:00 IST | Phase C | P-014 quota admission | STATUS: done
- Consult 009 / ADR-010: explicit public quota policy; identity-aware whole-request
  planning and nonexpiring owner-token mutex. Standalone engine remains registry-independent.
  Real separate-process races, exact overflow snapshots, Source/Session dedupe,
  gate/MCP and revocation-ledger growth covered. Independent reviewers reproduced an
  inherited-policy tenant-binding bug; all five regressions pass after correction.
- Independent QA: 37 passed in 23.05s; red-team: 13 passed in 8.93s. Reports:
  docs/qa/P-014.md and redteam-P-014.md. Owned cleanup/sentinel preservation PASS.
- Final `make check`: 519 passed, 1 skipped, 3 deselected, 1 xfailed in 138.99s;
  Ruff, tracked secret scan and check_numbers PASS. Initial full run found one obsolete
  metrics-public assertion; P-029 test follow-up now checks 401/no token and 200/admin.
  API fixtures clean only their own successful tenant creates; independent 31 passed.
- `make dogfood`: PASS=19 FAIL=0 EXPECTED-FAIL=3 STALE=0 SKIP=0, exit 0.
  S07 events overflow now PASS (429, no writes). Remaining expected failures are S08/S09
  input/error containment and S14 absent application metrics. Not strict all-scenarios PASS.
  Exact owned cleanup PASS, no leftovers; report scratch/dogfood/20261016T152457Z.md.
- Docker Desktop and the existing pinned DB container were restarted after downtime;
  unavailable-DB setup errors were not classified as product failures or passing tests.
- Limits: stable primary/protected keys/cooperating writers required; no failover fencing.
  Crashes/ambiguous writes strand admission until quiescent manual recovery. Full cap may
  reject new revoke/reinstate ledger nodes. Non-quota errors can retain earlier batch writes.
- No evaluation numbers produced; no push or Phase-C completion claim. Next: P-015.

### 2026-10-16 21:17 IST | Phase C | P-015 tenant roles | STATUS: done
- Consult 010 / ADR-011: separate stored agent/operator digests, legacy agent-only,
  explicit operator issuance/rotation. Tenant role checks replace global-header trust
  upgrades. Whole batches authorize before writes; HTTP MCP consumes per-message bearer
  headers without conflicting/invalid credential fallback. Defaults/hooks agent-only;
  explicit operator MCP invocation allowed, with domain dissent documented.
- Builder actual red: 14 failed in 9.20s. Core/HTTP/query lint green 26 passed plus
  same-session header-change test 1 passed. Registry create/issuance attacked concurrently;
  unique Tenant constraint/CREATE and write-first issuance prevent credential overwrite.
- Independent QA 10 passed in18.81s; combined focused91 passed in94.29s. Independent
  red-team16 passed in37.71s. Reports docs/qa/P-015.md and redteam-P-015.md; sentinel intact.
- Final `make check`: 582 passed,1 skipped,3 deselected,1 xfailed in274.01s; Ruff,
  tracked secret scan and numbers PASS. `secret_scan --history` PASS after staging newfiles.
  Earlier fullrun:1failed563passed; sole stale fake credential response fixed, ownership
  assertions retained. Root focused fixture cleanup12passed1.55s, sentinel unchanged.
- `make dogfood`:20PASS,0FAIL,3EXPECTED-FAIL,0STALE,0SKIP; exactownedcleanupPASS/zero
  leftovers. S22 agent+globaladmin escalation denialPASS. Remaining S08/S09=P-021,
  S14=applicationmetrics. Report scratch/dogfood/20261016T153741Z.md.
- Consumers: newtenantfiles save both roles, UI requests operator, CLI explicit issue/rotate;
  existingfiles preserved. Adapter local guards verified in Python/Node, notinstalledruntime.
  Scannerrole-shape tests actual2red then7green; no productioncredential output/commit.
- Material caveat: agent corroboration can produce descriptive preserved status; tested
  high-risk gate still blocks. README/KNOWN_ISSUES disclose status is not operator verification.
- No evalnumbers, provider/deployment claim or push. Next P-021, then P-020/P-036 and C gate.
