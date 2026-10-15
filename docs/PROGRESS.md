# CURRENT STATE (overwritten after every feature / checkpoint)

- **Phase:** P1 vertical slice; F-09/F-10/F-11 completed (Thu 21:39 IST). Phase 1 is not complete:
  installed runtime capture remains unverified, and F-08 is blocked by its free provider quota.
- **Last green implementation:** 4eb3a66 (F-09), preceded by 38b1376 (F-10) and 06c82f1 (F-11).
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1; 108 GB free disk.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.
- **Test state:** **245 passed** (`make check`, real FalkorDB; 31.58s), lint/secret/numbers PASS.
  A fresh clone+new venv of 4eb3a66 passed full pytest (245, 34.53s) and lint. Wheel built;
  all UI static assets included. History secret scan PASS after adding new files.
  Hook subprocess -> HTTP -> DB -> deny and actual UI -> persisted revoke -> reload verified.
- **Features [done]:** F-01 (QA PASS round 2), F-02 (PASS), F-03 (PASS), F-04 (PASS),
  F-05 + F-06 (PASS incl. red-team hardening), F-07 API/capture mapping (QA evidence exists),
  F-09 (independent QA + review + builder browser proof), F-10 and F-11 (QA + review PASS).
  F-07 installed-runtime capture/fidelity gaps remain open issue 12.
- **Local service:** root-owned Uvicorn on 127.0.0.1:8000 (session 92866, PID19808), demo tenant
  seeded healthy with 11 nodes. Credential is in ignored scratch/demo-demo.json; never print it.
  Browser QA used and removed a separate random tenant; main demo was not revoked.
- **No in-flight source edits.** OpenCode spike artifacts honestly record session startup only;
  tool before/after payloads are null, not fabricated. No paid fallback was used.
- **Material limits:** human/scanner authority is caller-asserted pending F-13; repeated unmatched
  file reads can create new Source ids; hook failures are fail-open. See KNOWN_ISSUES 11-14.
- **Next 3 actions:**
  1. F-07/F-13 capture hardening: stable Source identity across repeated reads and separated
     human/scanner authority. Write consult + failing repros before changing these trust boundaries.
  2. Verify installed Claude runtime with own synthetic capture if an already-authorized free path
     is available; F-08 remains blocked until free quota returns. Do not invent tool payloads.
  3. F-14 E1/E2 independent oracle/eval pipeline, then F-15 isolation/ACL and F-16 local/deploy path.
- **Blockers:** F-08 free_tier_limit (OpenCode1.19.0, free DeepSeek model: Free usage exceeded,
  subscribe to Go). Browser automation connection dropped twice during S8; Playwright CLI fallback
  completed the remaining local proof. Execution policy blocked deletion of ignored build/browser
  artifacts; left ignored. Temporary clone venvs remain in OS temp; no user data was deleted.
- **Human pending (batch 1 reply outstanding):** GitHub repo + remote URL, Discord answer, dogfood
  runtime choice, optional API keys in `.env`; Render account (Fri) not yet needed.

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

### 2026-10-16 01:05 IST | Phase P1 | F-07 audit fix + consult 007 capture trust (ADR-008) | STATUS: done
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

### 2026-10-16 00:30 IST | Phase P2 | F-14 E1 (contamination semantics) | STATUS: done (E2/E3 next)
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
