# Architecture decision records (plain language)

Format: `ADR-NNN | date | title` then Context / Decision / Alternatives / Consequences /
Evidence. Written so the human can defend each decision in plain words.

---

## ADR-000 | 2026-10-15 | Tracks: enter Track 2 (primary) + Track 1 (secondary)

**Context.** The launch blog says "you enter one track"; the rules page and FAQ say a
submission may be entered in any or all tracks and must name them. Organizers were asked
on Discord (pending answer, see `docs/00-HUMAN-CHECKLIST.md` step 2).

**Decision.** Default: enter **Track 2 — Agent Memory and Coordination** as primary and
**Track 1 — Agents That Act on Connected Data** as secondary; skip Track 3. Both are
substantiated by the product (memory lineage/coordination; revoke/gate acting on connected
data). If the organizers answer that only one track is allowed, we keep Track 2.

**Alternatives.** Enter one track only (under-uses the product); enter all three (Track 3
overlap is weak, would look padded).

**Consequences.** README names both tracks; the Discord answer is recorded here when it
arrives (ADR-000a). **Reversible:** yes, renaming in README/submission form.

---

## ADR-001 | 2026-10-15 | Windows development host: Docker for FalkorDB, cross-platform Python tooling

**Context.** The design pack (docs/09 §A) specifies the primary local path: the
`falkordblite` wheel's `redis-server` plus the official 4.22.1 Linux `.so` loaded as a
module — a Linux-only mechanism (ELF `.so`, glibc ≥ 2.39). The development host for this
build is **Windows 11** (Python 3.12 via uv, Docker Desktop 29.8.2 available, WSL2 Ubuntu
24.04 available). A Linux `.so` cannot be loaded by a Windows `redis-server`.

**Decision.** On this host, FalkorDB **v4.22.1 runs as the pinned Docker image**
`falkordb/falkordb:v4.22.1` with the mandatory server arguments
(`TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`).
The documented Linux/no-Docker path is still shipped and is the path used by the
production `Dockerfile` (Ubuntu 24.04 + wheel `redis-server` + pinned `.so`), so it is
exercised at deploy time. All repo tooling (start/stop DB, tests, checks) is invoked
through cross-platform Python entry points (`python -m pedigree.cli db start`, etc.) so
`make` targets work on Windows and Linux; `.sh` scripts remain for Linux users.

**Alternatives.** (a) Run everything inside WSL2 — rejected: splits the workspace across
filesystems (slow, awkward for the human), and the human's editors/agents are on Windows.
(b) Use FalkorDB Cloud Free from the start — rejected: 100 MB, no TLS, no persistence,
and the build must work offline.

**Consequences.** Local runs use Docker (RAM ~100-200 MB for the DB container); the
"no Docker" instructions in the README are marked as the Linux path and are verified in
the Docker build. **Reversible:** yes (swap `db start` implementation).

**Evidence.** `tech/bench/*` (4.22.1 verified on Linux by the pack authors);
`MODULE LIST` output recorded in `docs/PROGRESS.md` for the Docker container.

---

## ADR-002 | 2026-10-15 | Python 3.12 for the build environment

**Context.** Host has Python 3.10/3.12/3.13/3.14 + uv-managed 3.11/3.12. The project needs
Python ≥ 3.11; dependency wheels (falkordb 1.8.0, mcp 2.x, pydantic v2, hypothesis) are
safest on an intermediate version. Python 3.14 is very new; some wheels may lag.

**Decision.** Build and test on **CPython 3.12** (uv-managed 3.12.15), declared as
`requires-python = ">=3.11"`. CI/clean-clone checks use whatever 3.11+ interpreter is
present.

**Consequences.** Slight version skew vs the pack authors' 3.13 environment is acceptable
and recorded in eval result headers. **Reversible:** yes.

---

## ADR-003 | 2026-10-15 | Makefile delegates to a cross-platform Python CLI instead of shell scripts

**Context.** `make` is available on the host (GNU make 4.x via Chocolatey) but its default
shell is `cmd.exe`; the pack's scripts are POSIX shell. Rendering the same commands
nowhere near the docs' expectations would break `make test` on the human's machine.

**Decision.** The `Makefile` targets call `$(PY) -m pedigree.cli <cmd>` and
`$(PY) -m pytest`; `$(PY)` resolves to `.venv\Scripts\python.exe` on Windows and
`.venv/bin/python` elsewhere. POSIX `.sh` wrappers (`scripts/start-falkordb.sh`,
`scripts/fetch-falkordb.sh`, `scripts/clean_clone_check.sh`) are kept for Linux users and
are called by the Dockerfile.

**Consequences.** `make check` works identically on Windows and Linux. **Reversible:** yes.

---

## ADR-004 | 2026-10-15 | Ids allow `_`; artifacts are free-form paths (not ids)

**Context.** docs/01 §9 defines the id charset `^[A-Za-z0-9._:/@#-]{1,128}$`, which has no
underscore. But every auto-generated id in the design (`src_<hex>`, `mem_<hex>`, `act_<hex>`)
and the verified prototype's scenario ids (`s_web`, `m2`, `a_push`) contain `_`; strict
enforcement would reject the product's own ids. Separately, `artifacts` are file paths,
commit SHAs and URLs — on Windows they contain `\` and spaces — so reusing the id regex
for them would reject legitimate data.

**Decision.** Extend the id charset with `_` (one character added to the class) and validate
artifact strings with a separate rule: printable text, 1..512 chars
(`^[^\x00-\x1f]{1,512}$`). Node ids keep a strict allow-list; artifact strings are stored as
data only, never interpolated into Cypher.

**Alternatives.** Drop `_` from generated ids (rejected: uglier and diverges from the
docs' own examples) or relax ids entirely (rejected: weaker injection surface control).

**Consequences.** `graph_name()` is unaffected (tenant ids stay `[a-z0-9]{3,24}`).
**Reversible:** yes. **Evidence:** `tests/unit/test_config.py`, `tests/integration/test_core_scenario.py`.

---

## ADR-005 | 2026-10-15 | Tenant ids are validated at every engine boundary (QA finding)

**Context.** QA round 1 (session `ses_ec033eae7ffefekNuBi1yw4GM8`) proved that the engine
functions accepted any `tenant` string and wrote it verbatim into node properties (e.g.
`'not a valid tenant!'`). Injection was contained (all Cypher is parameterised), but invalid
tenants could be persisted. F-05 will derive the tenant from the bearer token only; until
then the engine itself must refuse bad tenants.

**Decision.** Add `config.validate_tenant()` and call it at the top of every engine entry
point (`record_source`, `remember`, `record_action`, `revoke`, `reinstate`), before any DB
access, so a rejected call performs **zero writes**.

**Alternatives.** Rely on F-05's token mapping alone (rejected: one forgotten call site
persists garbage); validate inside `graph_name()` only (insufficient: the engine may write
several graphs-related properties before naming one).

**Consequences.** One cheap regex check per call; invalid tenants raise typed
`InvalidArgument`. **Reversible:** yes. **Evidence:**
`tests/integration/test_tenant_guard.py` (bad tenant -> `InvalidArgument`, node count
unchanged for 8 bad values x each entry point); `docs/qa/F-01.md` finding 2.

---

## ADR-006 | 2026-10-15 | `:Revocation` lifecycle property is `state`, not `status`

**Context.** docs/01 §5 lists `status` for all entities, but a Revocation is not a belief:
its meaningful lifecycle is `running|done` (crash recovery keys on `state='running'`).
QA round 1 also found that `check_invariants` could not detect a *missing* `status`
(NOT-semantics on NULL), so both a real gap and the Revocation deviation were invisible.

**Decision.** Keep `state` as the single lifecycle property on `:Revocation` (no duplicate
`status` bookkeeping) and add `Q_INV_MISSING_STATUS` ("every :Node carries a status property
**except** :Revocation") so the gap is now detected everywhere else. The deviation from §5
is recorded here and in `docs/KNOWN_ISSUES.md`.

**Alternatives.** Add `status` to Revocation nodes duplicating `state` (rejected: two
fields that can drift; `done` is not in the status vocabulary anyway).

**Consequences.** Simpler crash-recovery reads; one documented model deviation.
**Reversible:** yes (add + backfill, one query). **Evidence:**
`tests/integration/test_schema.py::test_invariants_detect_missing_status`;
`docs/qa/F-03.md`.

---

## ADR-007 | 2026-10-15 | Gate rule 1 reads materialised containment; trusted-only corroboration

**Context.** docs/01 §6.6 rule 1 ("any relied node or ancestor status in
`revoked|tainted|quarantined` -> block if risk >= medium else warn") is ambiguous: literal
transitive ancestry would also warn/block actions relying on a `preserved` node or on an `ok`
descendant of one, contradicting scenario S8 ("its dependent stays `ok`") and the product's
preservation claim, while making the hook path pay a depth-12 BFS per relied id. Separately, the
red team measured (consult 006) that agent-asserted `CORROBORATED_BY` (forged through MCP)
launders a `preserved` status that then clears the gate, and that `by='human'` was the *default*
at every entry point.

**Decision.** Consult 006 (`docs/consults/006-gate-ancestor-scope/decision.md`, unanimous):
1. rule 1 keys on the relied node's materialised `status` (the revoke engine already resolved
   containment into `status` + `taint_parent`); `preserved`/`ok` pass rule 1;
2. a `preserved` node passes only with **trusted support** (`CORROBORATED_BY.by` in
   `human|scanner`); agent-asserted support gates the node exactly as `tainted`;
3. an `ok` node whose ancestor closure contains an untrusted-support `preserved` node is
   `reverify` at `effect='irreversible'` or `risk='high'` (path in the reason);
4. `relied_on` empty + a session read window containing a bad node -> `reverify` (never silent
   allow); empty window -> `allow` + `warning:no_lineage`;
5. `by` defaults to `agent` at every entry point (engine `corroborate`, REST, MCP);
   out-of-band callers pass `human`/`scanner` explicitly.
New invariant `Q_INV_OK_HAS_NO_BAD_PARENT` asserts no `ok` node has a bad `DERIVED_FROM`
parent, which is what makes reading `status` at the gate sound.

**Alternatives.** (A) literal ancestry (rejected: breaks S8/demo, maximises E3b benign
friction, per-hook BFS, and the attacker routes around it by omitting `relied_on` - measured).
Trust any status-ok corroborator (rejected: the attacker mints the corroborating source).
Propagate `containment_basis` in `compute_final` now (deferred: engine change that would
re-open F-02/F-03 QA; the gate-time ancestor audit covers the same case at high risk; tracked
in KNOWN_ISSUES for F-12/F-13).

**Consequences.** The gate stays a read-only decision function over materialised status; the
declassification signal moves from "any CORROBORATED_BY" to an out-of-band authority. **Reversible:**
yes - the gate is read-only and reverting to (A) is one BFS per relied id.
**Evidence:** `docs/consults/006-gate-ancestor-scope/{architect,redteam,domain,decision}.md`,
`tests/integration/test_gate_integration.py`, `tests/security/test_security_F11.py`.

---

## ADR-008 | 2026-10-15 | Incomplete gate evidence requires re-verification; recording is explicit

**Context.** Independent F-11 tests reproduced silent allow when untrusted support was
deeper than the traversal bound, and an Action left behind after an unknown-session error.
Missing dependencies discarded the gate verdict when recording failed.

**Decision.** Inspect an additional BFS level: a frontier beyond the bound requires
`reverify` with `lineage_truncated` at high risk/irreversible effect. Validate recording
prerequisites before writing. Missing anchor/session returns the verdict plus
`recording_error`, without an Action or invented edges. Return `action_id` only on success.
Apply matching policy audience consistently.

**Alternatives.** Unbounded traversal risks hook timeouts. Recording only known anchors
would make incomplete evidence appear complete. Throwing after writing creates ambiguous state.

**Consequences.** Deep benign ancestry can require manual verification. Callers distinguish
decision success from optional recording failure. Reversible response addition; no schema
change. **Evidence:** `tests/security/test_F11_adversarial.py`,
`tests/integration/test_gate_qa.py`; independent reports in `docs/qa/`.
