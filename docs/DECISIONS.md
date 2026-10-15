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
**Reversible:** yes. **Evidence:** `tests/unit/test_config.py`, `tests/test_ingest.py`.
