# F-05 API - Senior Architect consult `005-F05-api`

ADR-006: thin sync FastAPI over unchanged engine; tenant only from bearer lookup in registry graph `pedigree:registry`; one shared admin Db; no ORM. F-13 can harden without changing this contract.

## Recommendation
Option A: a shared admin `Db`, a storage-backed registry, and a tenant-resolving dependency. Request bodies are Pydantic v2 with `extra="forbid"` and never carry `tenant`. Every handler validates via `validate_id`, then uses `graph_name(tenant)` before calling the engine. All engine logic remains untouched.

## Why
- Tenant only from token; no override by body/query.
- Mutations already are atomic parameterised queries, so no `MULTI/EXEC`.
- Sync threadpool; timeouts bound stalls.
- Tokens hash-at-rest/rotatable; 30 s cache invalidates explicitly.
- Errors reuse `PedigreeError` statuses: validation 422, DB 503/504, catch-all 500 + correlation id.

## Options
- A: shared admin Db + registry graph + cached token map. **Recommended**.
- B: JSON-file tenant registry. Rejected: races with graph state.
- C: per-tenant ACL Db. Rejected for v1: Cloud Free ACL unverified and provisioning adds failure modes.

## Design
Registry node: `Tenant {id, token_sha256, created_at, node_cap, status}`, unique id. Token: `ped_<tenant>_<32 urlsafe>`; store only sha256; `hmac.compare_digest`.
Routes: `/healthz`, `/readyz`, `/metrics` (admin), `/admin/tenants`; engine: `/v1/sources`, `/memories`, `/actions`, `/revoke`, `/reinstate`, `/blame/{id}`, `/impact/{id}`, `/graph`, `/stats`. Future routes are additive.
Middleware: 256KiB body, correlation id, auth, rate bucket (120/min; revoke 10/min), metrics. `readyz`: DB ping + registry indexes.
Errors: `PedigreeError -> HTTP_STATUS`; validation 422; DB 503/504; else 500.

## Tests smallest first
1. healthz 2. readyz_down 3. admin_create_tenant 4. auth 5. no_tenant_field 6. error_contract 7. isolation_smoke.
Invariants: body `tenant` rejected; only `graph_name(tenant)` graph; unknown id `not_in_graph`; mutations leave `check_invariants` empty.

## Failure modes
DB down/slow -> readyz 503 and route 503/504. Lost tenant response -> retry idempotent or rotate. Cache invalidates on rotate. Reader stalls bounded by timeouts.
## Risks
Shared admin credentials wider blast radius than ACL users; cache/retry idempotency needs tests.
## Reversibility
High: remove api module/revert cli serve; registry graph remains inert; no engine/Cypher changes.