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
| 10 | 2026-10-15 | `BodySizeMiddleware` compares against a literal `256 * 1024` instead of `LIMITS["body_bytes"]` (identical value). | informational | cosmetic |
| 11 | 2026-10-15 | P-015 / ADR-011 replaces interim global-admin trust headers with stored tenant agent/operator roles. Agent trusted claims and revoke/reinstate reject; global X-Admin-Token cannot elevate an agent. Explicit operator REST/MCP calls are supported; MCP defaults and hooks require agent credentials. Legacy bearers retain agent privileges and need explicit admin operator issuance. Supplying an operator bearer to an agent grants that authority; host compromise is outside this boundary. | high | closed 2026-10-16; independent P-015 QA/red-team PASS |
| 12 | 2026-10-15 | Claude hooks have synthetic contract and real localhost HTTP subprocess proof, but no installed-runtime execution. Web/tool-description sources and shell file I/O are not captured. ~~Repeated unmatched file reads create separate Source ids~~ - identity now converges on `(uri, content_hash)` (ADR-008), so revoking one copy covers future identical reads. | high | installed-runtime capture still open (F-07/F-08); source identity closed 2026-10-16 |
| 13 | 2026-10-15 | Runtime registry uses ped:registry while unused REGISTRY_GRAPH and original spec say pedigree:registry. Reserved tenant id prevents collision; deployment/ACL docs must use the actual name until migrated. | medium | open, F-13 consistency |
| 14 | 2026-10-15 | Shell classification is a regex heuristic, not a sandbox. Hook network/malformed-payload failures are fail-open. | medium | documented, F-11 |
| 15 | 2026-10-15 | The earlier OpenCode spike was quota-blocked. The free-only recheck captured one genuine read-tool before/after pair with a temporary observation plugin; the session final response timed out. An opt-in read-only adapter slice now exists (`adapters/opencode/`, ADR-009) and is hook-replay verified against a live API; installed-session acceptance and write/edit/shell coverage remain unverified. | medium | F-08 implementing; see opencode-recheck-2026-10-16.md, docs/qa/F-08.md, docs/qa/redteam-F-08.md |
| 16 | 2026-10-16 | Sources recorded with agent bearers are untrusted, including ordinary file/rules captures, so gate rule 3 `untrusted_influence` fires on irreversible/high-risk actions built on captured evidence. Explicit trusted claims require the tenant operator bearer. The friction cost is NOT MEASURED (no E3b benign corpus); engine/seed and explicit operator paths can create trusted evidence. | low | documented (ADR-011) |
| 17 | 2026-10-16 | Source identity residuals: a hash-less read after a hashed one of the same uri creates a second node; capture ids from an earlier batch are not resolvable as aliases (only in-batch aliases are). | low | documented (ADR-008) |
| 18 | 2026-10-16 | Per-tenant DB ACL users are **verified but not wired**: `tests/security/test_acl_mechanism.py` provisions real ACL users (scoped `~ped:<tenant>` / `~ped:<tenant>:wi:*`) and proves cross-namespace denial on v4.22.1, but the service still connects with the shared admin credentials. Tenant isolation in the shipped service is therefore API-level (bearer token -> one graph per tenant, cross-tenant ids 404), with the ACL mechanism proven and the wiring tracked for F-16 hardening. | medium | open (F-16) |
| 19 | 2026-10-16 | `Db` now holds one FalkorDB connection **per thread** (measured: 160 writers on one connection produced `unavailable`). A deployment that creates unbounded threads therefore creates unbounded connections; the API threadpool is bounded, and `reset()` drops them. | low | documented, mitigated |
| 20 | 2026-10-16 | Engine writes assume the tenant graph schema exists (`ensure_schema`); the API runs it on every authenticated request, but a direct engine caller (seeder/test) must create it first - `record_source` on a schema-less graph can create duplicate identities under concurrency because the constraints are missing. | low | documented (F-10/F-15 tests call ensure_schema) |
| 21 | 2026-10-16 | Isolation and E3 scenario fixture teardown previously enumerated and deleted all registered tenants. It now tracks only successful creates owned by that fixture, preserves a real pre-existing sentinel, and reports retained/unknown cleanup failures. Earlier runs cannot establish preservation of pre-existing data. The dedicated synthetic demo was re-seeded after repair; no recovery of arbitrary deleted data is claimed. | high | repaired; docs/qa/test-fixture-ownership.md and e3-fixture-ownership.md PASS; lazy suite sentinel added |

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
F-17 concurrency admission is process-local; checkpoint/restore remains unbuilt.
F-18 WCC analysis remains unbuilt. These subset passes do not close the ACL service-wiring
item or establish multi-process what-if coordination.
