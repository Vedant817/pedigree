# CURRENT STATE (overwritten after every feature / checkpoint)

- **Phase:** P0 - Foundation + spikes (Phase 0 acceptance tests ALL green; tagged `phase-0` at commit fd948a0)
- **Last green commit:** 9ec9c3d
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1; 108 GB free disk.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.
- **Test state:** **62 passed** (full suite, real FalkorDB) | `make check` green | AT0.1-AT0.6 verified
  on a clean clone (`scripts/clean_clone_check.sh` PASS) | secret-scan `--history` gate green.
- **Features [done]:** F-01 (schema/skeleton/self-heal round-2 PASS), F-02 (ingest), F-03 (revoke).
- **Next 3 actions:**
  1. F-04 blame + impact (tests -> implement -> verify) -> `docs/qa/F-04.md`.
  2. Phase 1 P0 slice begins: F-05 REST API + registry + tenant auth; F-06 MCP; F-07/F-08 capture adapters.
  3. F-10 scenario JSON + `seed_demo.py` seeder.
- **Blockers:** none open. Independent `qa-senior` subagent round 2 hit the provider's free-tier
  rate limit (not a product defect); first findings covered by role-switch re-verification.
- **Human pending (batch 1 reply outstanding):** GitHub repo + remote URL, Discord answer, dogfood
  runtime choice, optional API keys in `.env`; Render account (Fri) not yet needed.

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
