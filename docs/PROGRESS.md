# CURRENT STATE (overwritten after every feature / checkpoint)

- **Phase:** P1 vertical slice; F-11 gate completed ahead of the phase order (Thu 21:21 IST).
- **Last green implementation:** F-11 gate, pending commit below; prior HEAD 84ba350.
- **Environment:** Windows 11 dev host; Python 3.12.15 (uv `.venv`); Docker Desktop 29.8.2 running
  FalkorDB `falkordb/falkordb:v4.22.1` (pinned; mandatory args); Node v24.13.1; 108 GB free disk.
- **Deadlines:** feature freeze Sun 2026-10-18 15:00 IST; submit target Sun 21:00 IST; hard stop 23:59 IST.
- **Test state:** **202 passed** (`make check`, real FalkorDB); independent QA and review PASS.
  History secret scan PASS. Real hook subprocess -> HTTP -> FalkorDB -> deny verified.
  Installed Claude Code runtime remains unverified; prior P0 clean-clone proof is historical.
- **Features [done]:** F-01 (QA PASS round 2), F-02 (PASS), F-03 (PASS), F-04 (PASS),
  F-05 + F-06 (PASS incl. red-team hardening), F-07 API/capture mapping (QA evidence exists),
  F-11 (QA + review PASS). F-07 installed-runtime capture/fidelity gaps remain open issue 12.
- **In flight:** F-08 isolated OpenCode payload spike; F-10 synthetic scenario seeder.
- **Material limits:** human/scanner authority is caller-asserted pending F-13; repeated unmatched
  file reads can create new Source ids; hook failures are fail-open. See KNOWN_ISSUES 11-14.
- **Next 3 actions:**
  1. Commit F-11 verified implementation and check the committed tree from a fresh clone.
  2. F-08 real-payload spike -> plugin; F-09 UI v1 using authenticated persisted graph data.
  3. Finish F-10 scenarios/`make demo`, independent QA, then address capture authority/identity.
- **Blockers:** none open. Provider free-tier rate limits interrupted two QA rounds (not product
  defects); fallback per docs/04 §12 (role-switch with fresh-shell re-runs).
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
