# Known issues and limits

Open items are tracked here (with a link to the failing test or the evidence). A feature
that cannot be finished goes here rather than being silently dropped.

| # | Date | Item | Severity | Status |
|---|---|---|---|---|
| 1 | 2026-10-15 | Development host is Windows; FalkorDB 4.22.1 runs via the pinned Docker image instead of the Linux `.so`+wheel path. The Linux/no-Docker path is shipped (`scripts/*.sh`) and is exercised by the production `Dockerfile`. | low | accepted (ADR-001) |
| 2 | 2026-10-15 | The user's home directory `C:\Users\vedan` is itself a git repository (no commits). The Pedigree repo is a separate repository nested inside it; git commands inside `pedigree/` use the local `.git`. | informational | noted |
| 3 | 2026-10-15 | FalkorDB Cloud Free tier has no TLS and no persistence; if used for the hosted demo it will hold synthetic demo data only. | low | documented |
| 4 | 2026-10-15 | `scripts/start-falkordb.sh` / `fetch-falkordb.sh` support the Linux no-Docker path. The local F-16 container build exercises the pinned-module mechanism; a separate bare-host Linux deployment is not claimed. | low | container path verified; bare-host qualification open (F-16) |
| 5 | 2026-10-15 | `make demo` now seeds synthetic S1/S8 idempotently, preserves changed lifecycle/support authority, and keeps credentials in ignored scratch. | low | resolved, F-10 |
| 6 | 2026-10-15 | `docs/WALKTHROUGH.md` exists and is referenced by the README; human walkthrough review and final publication remain part of F-23. | informational | document present; human review pending (F-23) |
| 7 | 2026-10-15 | Static-Cypher lint is a guard-rail, not a proof: it cannot see strings assembled through variables or external data. Coverage now includes f-strings, `.format`/`.replace`/`.join` on literals, concatenation and `%`. Manual review + parameterised query constants remain the primary control. | low | documented |
| 8 | 2026-10-15 | `:Revocation` nodes carry `state` (running/done) instead of `status`; the missing-status invariant explicitly exempts them. Deviation from docs/01 §5 recorded in ADR-006. | low | accepted (ADR-006) |
| 9 | 2026-10-15 | `POST /v1/events` applies operations in order and aborts on the first typed error, so a failing batch leaves the earlier events applied (no cross-event atomicity). Acceptable for the idempotent capture channel; documented in `docs/qa/F-07.md`. | low | documented |
| 10 | 2026-10-17 | P-021 replaces the old declared-length check with actual-byte HTTP admission using the shared body limit, including chunked REST/MCP. Stdio line allocation remains owned by the MCP SDK. | informational | repaired; independent P-021 QA/red-team PASS |
| 11 | 2026-10-15 | P-015 / ADR-011 replaces interim global-admin trust headers with stored tenant agent/operator roles. Agent trusted claims and revoke/reinstate reject; global X-Admin-Token cannot elevate an agent. Explicit operator REST/MCP calls are supported; MCP defaults and hooks require agent credentials. Legacy bearers retain agent privileges and need explicit admin operator issuance. Supplying an operator bearer to an agent grants that authority; host compromise is outside this boundary. | high | closed 2026-10-16; independent P-015 QA/red-team PASS |
| 12 | 2026-10-15 | Claude hooks have synthetic contract and real localhost HTTP subprocess proof, but no installed-runtime execution. WebFetch/WebSearch and bash `cat`/`head`/`curl`/`wget` reads are captured from synthetic payloads (`tests/fixtures/claude/`, P-017). Glob/Grep, shell writes, and tool-description sources are still not captured. Real Claude Code session fixtures are human-only. The pre-tool gate still applies the ADR-007 read-window floor, so a later command that does not name its own inputs asks when the session has read a now-revoked node. ~~Repeated unmatched file reads create separate Source ids~~ - identity now converges on `(uri, content_hash)` (ADR-008). | high | installed-runtime capture still open; synthetic web and shell-read capture landed 2026-10-17 |
| 13 | 2026-10-15 | Runtime registry uses ped:registry while unused REGISTRY_GRAPH and original spec say pedigree:registry. Reserved tenant id prevents collision; deployment/ACL docs must use the actual name until migrated. | medium | open, F-13 consistency |
| 14 | 2026-10-15 | Shell classification is a regex heuristic, not a sandbox. Hook network/storage/malformed-payload failures now deny pre-tool execution; offline capture is retained in a scoped durable spool. Actual installed Claude execution remains unverified. | medium | delivery/gate implementation tested locally; installed acceptance open |
| 15 | 2026-10-15 | Genuine installed OpenCode read/write/edit/bash capture and revoked-input denial are recorded in docs/qa/opencode-native-local.md. Arbitrary shell provenance and cross-session artifact linkage remain unsupported. Durable restart markers and independent native review are in progress. | medium | F-08 QA |
| 16 | 2026-10-16 | Sources recorded with agent bearers are untrusted, including ordinary file/rules captures, so gate rule 3 `untrusted_influence` fires on irreversible/high-risk actions built on captured evidence. Explicit trusted claims require the tenant operator bearer. The friction cost is NOT MEASURED (no E3b benign corpus); engine/seed and explicit operator paths can create trusted evidence. | low | documented (ADR-011) |
| 17 | 2026-10-16 | Source identity residuals: a hash-less read after a hashed one of the same uri creates a second node; capture ids from an earlier batch are not resolvable as aliases (only in-batch aliases are). | low | documented (ADR-008) |
| 18 | 2026-10-16 | Tenant database identities are now selected by REST/MCP/admin recovery after live bearer resolution. Dedicated ACL secret, namespace restrictions and no-admin-fallback behavior have real DB tests; deployed identity selection requires final-image verification. | medium | implemented; independent local review and runtime evidence tracked separately |
| 19 | 2026-10-16 | `Db` now holds one FalkorDB connection **per thread** (measured: 160 writers on one connection produced `unavailable`). A deployment that creates unbounded threads therefore creates unbounded connections; the API threadpool is bounded, and `reset()` drops them. | low | documented, mitigated |
| 20 | 2026-10-16 | Engine writes assume the tenant graph schema exists (`ensure_schema`); the API runs it on every authenticated request, but a direct engine caller (seeder/test) must create it first - `record_source` on a schema-less graph can create duplicate identities under concurrency because the constraints are missing. | low | documented (F-10/F-15 tests call ensure_schema) |
| 21 | 2026-10-16 | Isolation and E3 scenario fixture teardown previously enumerated and deleted all registered tenants. It now tracks only successful creates owned by that fixture, preserves a real pre-existing sentinel, and reports retained/unknown cleanup failures. Earlier runs cannot establish preservation of pre-existing data. The dedicated synthetic demo was re-seeded after repair; no recovery of arbitrary deleted data is claimed. | high | repaired; docs/qa/test-fixture-ownership.md and e3-fixture-ownership.md PASS; lazy suite sentinel added |
| 22 | 2026-10-17 | A rejected request body (wrong content type, unknown field, bad value) returned the same detail-free `422 invalid_argument` envelope as an authored rejection, and nothing was logged, so the cause was invisible from outside. The reported write-path blocker reproduces with a form-encoded body (the curl `-d` / PowerShell `-Body` default) or an unknown field; the same endpoint returns `200` with `Content-Type: application/json`. Validation failures and authored 422 reasons are now logged server-side with the request correlation id (field paths/types and the static reason only — never values). | low | repaired 2026-10-17 |
| 23 | 2026-10-17 | On `POST` routes FastAPI validates the body before the in-handler authorization check, so a bad token plus a malformed body returns `422` rather than `401`/`403` (schema-shape oracle; no state change; valid requests are still denied). Keep-as-is decision: the ordering fix is cross-cutting and the exposure is a schema shape, not data. | low | accepted; P-003 QA F1 / redteam-P-003 F2 |
| 24 | 2026-10-17 | MCP over HTTP answers `initialize`/`tools/list` and the `pedigree_health` tool without a credential (SDK handshake plus a health probe with no tenant scope). Tenant-scoped tools and every write still require a valid token or are refused. | low | accepted posture; redteam-P-003 F1 |

What-if F-17 and source audit F-18 have independent QA/red-team PASS for their local subsets.
P-021's first builder event-test teardown used a nonexistent DB helper and left five
new test fixtures whose exact IDs were not retained. Future teardown is corrected;
unknown historical IDs were left alone. Later sentinel passes do not prove those
earlier leftovers were removed. No unrelated data deletion was observed.
Lifecycle `preserved` is descriptive support state, not operator verification: an
agent-authored corroboration edge to a healthy Source can produce it. The gate
separately checks human/scanner attestation and blocks high-risk use when only agent
support exists. P-015 red-team reproduced `preserved` with `by=agent` and a blocking
gate; do not treat the status label alone as trusted containment.
P-014 quota admission requires one stable Redis/Falkor primary and coordination keys
protected from eviction or loss. A crash or uncertain mutation can strand a nonexpiring
tenant mutex. Recovery requires stopping writers and confirming DB work is quiescent
before deleting the exact key; failover with live writers is outside this guarantee.
A full graph can reject revoke/reinstate when a new ledger node is needed. See
[the quota contract](fixes/P-014.md) and ADR-010 for this availability tradeoff.
F-17 what-if concurrency admission is process-local. Offline checkpoint/restore is
implemented with stopped-writer acknowledgement, durable journals and AOF compaction;
independent acceptance remains pending. F-18 WCC and ACL service wiring are implemented
and tested locally. These changes do not establish multi-process what-if coordination.

P-020 authentication now performs one indexed live digest query; local latency probes
are acceptance evidence, not a worst-case or production guarantee. Rate accounting is
shared by REST/MCP and both roles within one instance, with separate read/write
budgets. Extra workers and restarts multiply or reset those limits. Failed-auth
backoff can temporarily deny a valid user sharing a blocked peer/NAT; requests
already authenticating concurrently are not bounded by completed failure counts.
Shipped Uvicorn launch paths disable proxy-header rewriting. Custom reverse proxies
must establish a trustworthy peer boundary rather than accepting forwarded identity.
See [P-020 QA](qa/P-020.md) and [red-team evidence](qa/redteam-P-020.md).

[SECURITY.md](../SECURITY.md) records the trust model and operational assumptions.
Its private disclosure contact remains an explicit human TODO before public release.
The final [Phase C security review](qa/phase-C-security.md) retains the optional ACL
secret skip and the strict F-08 read-window watchdog xfail; neither proves deployed
DB isolation or complete installed-runtime capture.

## Pinned-engine AOF replay defect (2026-10-18)

Two isolated recovery test volumes failed hard restart with exit 139 while replaying
schema effects for already-deleted historical graphs. Both volumes are retained for
diagnosis; the original crashed volume was untouched. Offline recovery now completes
a fresh AOF rewrite before each maintenance reservation/recovery, and its consolidated
crash tests passed. This mitigation does not fix general v4.22.1 persistence behavior.
Orderly production-container restart evidence does not close arbitrary host-crash
durability. Treat this as a high-severity production qualification blocker pending
independent review and an upstream-supported resolution or verified operational limit.
See [the reproduction and mitigation evidence](qa/F-17-offline-recovery-local.md).
