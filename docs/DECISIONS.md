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
---

## ADR-008 | 2026-10-15 | Source identity is derived from the artifact; trust needs the operator credential

**Context.** Two measured capture holes (red-team consult 006/007): (1) `record_source` minted a
new id per call, so two identical reads produced two Source nodes with the same uri, revoking one
left its twin `ok`, and 200 identical reads burned 200 quota units; (2) authority was
caller-asserted - any bearer-token holder (i.e. the agent) could POST `/v1/corroborate` with
`by="human"` (which ADR-007 made the gate's trusted-support signal), mint a `web` source with
`integrity="trusted"`, claim `kind="human"`, or overwrite a real human attestation
(`MERGE ... SET r.by`).

**Decision.** `docs/consults/007-capture-trust/decision.md`:
1. **Derived identity.** `Source(uri)` + `Source(content_hash)` exact-match indexes and the
   composite unique constraint `Source(uri, content_hash)` (measured expressible on v4.22.1 once
   the indexes are OPERATIONAL; a uri-only constraint is deliberately absent - it rejects a
   legitimately changed page). `record_source` does one atomic `MERGE` on `(tenant, uri,
   content_hash)` - or `(tenant, uri)` without a hash - so repeated reads converge on one node and
   the same uri with a new hash is a new version whose old hash stays revocable. A caller id names
   the node at creation only. `POST /v1/events` resolves in-batch references through an alias map.
2. **Structural authority.** The agent channel can only downgrade: `/v1/sources` and `/v1/events`
   record **untrusted** for an agent token whatever the body claims (integrity/kind/runtime are not
   credentials) and reject trusted-by-default kinds without the operator credential; MCP
   `pedigree_record_source` always records untrusted; MCP `pedigree_corroborate` accepts only
   `by="agent"`; REST `/v1/corroborate` accepts `human`/`scanner` only with a matching
   `X-Admin-Token` (constant-time compare). The in-process engine keeps kind-based defaults so the
   seeder still produces human-attested demo sources.
3. **Write-once-then-upgrade corroboration.** `Q_CORROBORATE` keeps an existing `by` unless the new
   value is `human|scanner`.

**Alternatives.** Registry `role='human"` tenant token (rejected: on one host it moves "forge a
string in a body" to "read a string from a file" the agent can also read, and it changes the
registry schema). Caller-supplied stable ids only (rejected: the hook cannot mint one without
hashing the artifact - exactly the measured 3-nodes-per-path bug). Trusting `via` tags (rejected:
MCP writes `via='cite'`, identical to a genuine citation, measured).

**Consequences.** Captured Sources are untrusted over HTTP, so gate rule 3 `untrusted_influence`
applies to irreversible/high-risk actions built on them (friction measured later in E3b).
KNOWN_ISSUES 11/12 close for the shipped surface; a forged capture payload and a compromised host
stay documented residuals. **Reversible:** identity = 2 query constants + 1 DDL; authority =
route-level gating; no revoke/blame/gate algorithm change. **Evidence:**
`docs/consults/007-capture-trust/{redteam,domain,architect,decision}.md`,
`tests/integration/test_source_identity.py`, `tests/security/test_capture_trust.py`.


## ADR-009 | 2026-10-16 | OpenCode observed read views and explicit read-only enforcement

**Context.** Genuine installed OpenCode read payloads exist; a bounded native-write probe
failed at the free provider before tool execution. The old plugin sketch does not match
the actual API. Hashing current filesystem bytes would falsely identify a prior partial read.

**Decision.** Ship an explicitly enabled read-only adapter slice. Hash the observed display
view with a versioned range/representation namespace; keep contents and absolute paths local.
Use actual REST schemas, pair runtime call/session identities, deny block/reverify/outages,
and unconditionally deny unsupported tools. No operator token or agent trust upgrade.
F-08 remains implementing for full coding-agent capture; no installed write/approval/coverage claim.

**Alternatives.** Guessing write/action metadata or silently allowing uncaptured tools was
rejected. Durable replay/health state remains F-22; the read-only slice cannot automatically
execute side-effecting tools even after a restart. This restriction is explicit in install docs.

**Consequences.** This slice supports read-only inspection, not normal coding sessions.
Read-view hashes do not match whole-file artifact keys; cross-session write linkage remains
unsupported. All three consultants recommended the observed-read-first boundary.

**Evidence.** docs/consults/008-opencode-capture/{question,domain,architect,specialist,decision}.md;
genuine read fixture and separate opencode-write-recheck-2026-10-16.md. Implementation:
`adapters/opencode/**` (37 builtin Node tests), `tests/integration/test_opencode_plugin.py`
(live API + FalkorDB 42201 hook replay), `tests/security/test_security_F08.py`. Review:
`docs/qa/F-08.md` (FAIL on the tracked secret-scan canary; stale-doc findings) and
`docs/qa/redteam-F-08.md` (Windows ADS/drive-relative path bypass, case-split identity,
latch-ring and read-window eviction disclosures); fixes and disclosures landed in the
post-review commits. Independent QA must precede a shipped-subset claim.

## ADR-010 | 2026-10-16 | Request-wide quota admission with explicit recovery

**Context.** Independent count-before-create checks raced on real FalkorDB 42201:
consult 009's cap-one probe admitted four nodes. A write-first graph barrier fixed
that probe but did not establish safety for a sequential multi-query events batch.
The interrupted registry-coupled engine patch also broke standalone callers.

**Decision.** Authenticated REST/MCP creators inject an explicit tenant quota policy.
An owner-token Redis mutex covers identity planning, physical-node count and all
request writes. Nested creators inherit the same policy and validate tenant binding.
The mutex has no expiry; ambiguous writes retain it. Source and Session deduplication
counts actual new identities. Revocation ledger growth is reserved before state changes.
Quota rejection makes no batch mutations; other errors retain sequential partial writes.
Trusted standalone engine calls remain uncapped unless given an explicit/inherited policy.

**Alternatives.** Process-local locks cannot serialize separate service workers.
Expiring leases without fencing permit a paused writer to race a successor. Neither
count-and-create nor a single-query experiment proves whole-request admission.

**Consequences.** Supported operation requires one stable primary, no coordination-key
eviction/loss and cooperating public writers. This is not failover fencing. Crashes
can block later writes until all writers stop and DB work is confirmed quiescent;
only then may an operator remove the exact tenant key. A full graph can reject a
safety operation needing another ledger node. Future DB ACL wiring must include
the coordination namespace. No cap or graph schema migration is introduced.

**Evidence.** docs/consults/009-p014-quota/decision.md; tests/unit/test_quota.py;
tests/integration/test_p014_quota.py; independent docs/qa/P-014.md and
docs/qa/redteam-P-014.md, including separate-process races and exact snapshots.

## ADR-011 | 2026-10-16 | Tenant agent and operator credentials

**Context.** Shared tenant bearer authority permits an agent to revoke/reinstate;
the interim global-admin trust header is not a tenant role. FIX_PROMPT C1 requires
separate hashed role credentials and forbidden responses for agent trust claims.

**Decision.** Consult 010: resolve explicit stored roles by digest, legacy tokens
agent-only, additive agent/operator issuance with explicit administrative rotation.
Shared REST/MCP capability checks precede writes; global admin headers cannot elevate
an agent. Full event batches reject prohibited assertions before mutation. Normal
captured files remain untrusted agent evidence. Deployment administration remains
separate from tenant operations. HTTP MCP consumes bearer headers and rejects
conflicting tool credentials, with no invalid-credential fallback.

**Alternatives/dissent.** Domain recommended agent-only MCP. Architect and red-team
recommend explicit operator MCP requests to satisfy C1's operator-can acceptance;
choose this interpretation while requiring agent-only shipped defaults and hooks.
Prefixes alone cannot grant roles. Silent startup operator issuance cannot recover
the original secret and risks accidental privilege.

**Consequences.** UI and operator-positive tests need operator credentials; legacy
users need explicit operator issuance. Anyone who supplies an operator credential
to an agent grants it that authority. No host-compromise defense is claimed.
Indexed authentication and rate limiting remain P-020. Authorization and migration
need independent real REST/MCP QA before closure.

**Evidence.** docs/consults/010-p015-roles/{domain,architect,specialist,decision}.md;
domain's owned real-DB 42201 property/migration probe. Implementation uses the
existing Tenant(id) index/unique-constraint helper with CREATE, and a write-first
credential_epoch update before conditional operator issuance. Builder separate-client
races admitted one valid creation/issuance; independent tests/reports pending.

## ADR-012 | 2026-10-16 | Validate batches and contain SDK diagnostics

**Context.** Dogfood reproduces malformed event scalars as Python 500 messages.
Consult 011 measured control characters persisting or failing internally on 42201.
Installed MCP2.3 can echo rejected inputs or discard extras before tool code runs;
sanitizing engine lambdas alone cannot contain those errors.

**Decision.** Shared strict raw/canonical validation preserves documented aliases,
rejects malformed shapes/extras/unknown operations before batch writes, and keeps
existing caps/role/quota behavior. Identity fields reject controls without rewriting;
prose explicitly permits LF/tab. Bounded pure ASGI actual-byte admission protects
REST/MCP; installed SDK limit is configured too. Safe MCP call/transport boundaries
cover argument validation and auth faults. Static response messages/generated IDs,
safe typed details and class/frame diagnostics replace raw exception rendering.

**Alternatives.** Silent normalization hides unsupported capture. Raw exception
logging can expose a credential embedded in a cause. Content-Length alone does not
bound chunked requests. SDK defaults are not a shared strict application contract.

**Consequences.** Unknown-event ignore and permissive scalar coercion intentionally
become typed errors. Diagnostics lose raw exception messages but retain safe class,
operation, correlation and frame metadata. No installed agent/deployment claim.

**Evidence.** docs/consults/011-p021-validation/{domain,architect,specialist,decision}.md;
real controls and installed SDK probes; test-first implementation/review pending.

Implementation evidence: independent docs/qa/P-021.md PASS and redteam-P-021.md
PASS. MCP stdio uses a public runner override with isolated, shape-checked observed
SDK 2.3 `_lowlevel_server` plumbing because no public stream hook exists; its
receive/clone boundary sanitizes parser failures before dispatch. HTTP body limits
do not bound SDK stdin-line allocation. Actual TCP/stdio tests qualify this dependency.

## ADR-013 | 2026-10-17 | Indexed live authority and shared request admission

**Context.** Role-aware registry misses still scan tenants; REST charges twice and
shares reads with writes, while MCP has no matching rate admission. A prefetched
authority dictionary would regress live cross-process revocation/rotation.

**Decision.** Consult 012: one indexed digest OR query, stored-role/status checks,
ambiguity rejection and no authority cache. One locked, bounded per-instance limiter
is shared by REST and mounted MCP. Classify once, reserve all applicable buckets
atomically before protected work, separate reads/writes and retain destructive-operation
bounds. Failed-auth peer backoff uses a trustworthy transport peer, with shared-IP
denial tradeoff and disabled proxy rewriting in shipped launch paths.

**Alternatives.** Startup token dictionaries can be stale. Independent protocol
buckets and nested charging permit bypasses or halve advertised capacity. Evicting
live exhausted keys resets limits. Outcome accounting does not bound already-in-flight
authentication work, and per-process limits are not distributed enforcement.

**Consequences.** Additive credential indexes; no credential migration. A restart or
another worker has independent rate state. State saturation fails closed; valid callers
sharing an exhausted peer can be temporarily denied. Custom reverse-proxy deployments
must establish an explicit trusted peer boundary.

**Evidence.** docs/consults/012-p020-auth-rates/{domain,architect,specialist,decision}.md;
real 42201 indexed plans, nullable-slot and ambiguity probes; implementation/review pending.

## ADR-014 | 2026-10-17 | Separate deployment processes and freeze setup dependencies

Phase D chooses a non-root python:3.12-slim API plus a separate pinned FalkorDB
Compose service. Frozen uv installs, private persistent demo credentials and
fail-closed seed/startup replace root/dev installs and detached shell DB ownership.
No-Docker Linux setup owns its process/data/port and verifies module42201; native
macOS and hosted CI are not claimed from source inspection. Demo mode disables
deployment-admin HTTP routes; a local operator demo is not a public read-only
deployment. Optional public hosting is deferred. Consult013 domain/architect/DevEx
were unanimous; glibc compatibility and volume ownership require actual runtime QA.
See docs/consults/013-phase-d-runtime/decision.md for acceptance and reversibility.

## ADR-015 | 2026-10-17 | Reinstate recomputes under the remaining roots; corroboration is lazy; "healthy" means status ok

**Context.** P-012's `reinstate` blanket-reset a root's descendants before re-reading the
revoked-root set, so a descendant that was itself revoked was erased from R and came back
`ok` (`A→B→Cc`; revoke A, revoke B, reinstate A gave `B=ok`). The fix landed in `7045e39`
but left the specification inconsistent with it: `docs/01` §6.3 and F-03 described the
buggy blanket reset, and the oracle review (`docs/consults/008-p012-reinstate/oracle.md`,
verdict **NOT YET**) refuses to accept an oracle written from text that describes the bug.
Two more points were under-specified: when corroboration takes effect, and what "healthy
support" means.

**Decision.** (1) `reinstate(r)` = `R := R \ {r}`, then recompute the whole status map from
structure under the remaining root set `R`, with `R ∪ {r}` as the discovery seed set; nodes
in `R` are never reset (a revoked root wins even as a descendant), and only `r`'s
`revoked_at`/`reason` markers are cleared. (2) `corroborate` stays **lazy**: it adds the
edge and changes no status; support is effective as of the last recompute (the next
revoke/reinstate). (3) A memory is `preserved` iff it has a bad parent and a
`CORROBORATED_BY` source whose **status is `ok`**; `by` (agent/human/scanner) and
`integrity` do not enter the status recurrence. (4) The invariant for the P-012 class is
I-a (`revoked_at IS NOT NULL AND status <> 'revoked'` == 0) plus the existing I-b/I-c —
**not** the literal "no node is ok/preserved while having a revoked ancestor lacking
trusted support" prose: `preserved` with a revoked ancestor is the feature, a transitive
ancestor walk is redundant once I-a/I-b/I-c hold on a DAG, and a row-based check
false-positives on a legitimately reinstated root (`Revocation` rows are history).

**Alternatives.** Making `corroborate` recompute (stronger but changes a public
behaviour; needs its own acceptance criteria and cost analysis). A row-based invariant
(rejected: verified false positive on the reinstated root, 2 rows for A). Deleting the
reinstated root's `Revocation` row (would erase audit history; `domain.md` §4.3 says
rows are history). Implementing the literal ancestor-walk invariant (rejected as above).

**Consequences.** The docs, the from-scratch oracle (`tests/oracle.py::global_fixpoint`,
which reads only `nodes`/`parents`/`support`/`R`), the op-comparison driver
(`tests/integration/test_reinstate_oracle.py`) and the invariant check now state the same
contract, so a red battery means a real divergence rather than a doc/oracle mismatch. No
engine change is implied by this ADR beyond `7045e39`; `corroborate` latency is unchanged.

**Evidence.** `docs/fixes/P-012.md` (acceptance criteria restating the review's §7);
`docs/qa/P-012.md` (raw 300-example run, mutation red/green, wall time);
`tests/unit/test_p012_oracle.py` (hand cases, drift guard against `evals.oracle` on its
valid domain, import meta-test); `tests/integration/test_p012_invariant.py` (I-a
negative test); `tests/integration/test_reinstate_oracle.py` (DB property battery).
