# F-05 - REST API + tenant registry + bearer auth

Status: qa | Tests: `tests/integration/test_api.py` | QA: in progress

## Behaviour
- FastAPI service `pedigree.api.app:create_app` exposes:
  - `GET /healthz`, `GET /readyz`, `GET /metrics`
  - `POST /admin/tenants`, `GET /admin/tenants` (bootstrap-unauthenticated until first tenant; after that, `X-Admin-Token` must match `PEDIGREE_ADMIN_TOKEN`)
  - `POST /v1/sources`, `/v1/memories`, `/v1/actions`, `/v1/corroborate`, `/v1/sessions`, `/v1/sessions/read`
  - `POST /v1/revoke`, `POST /v1/reinstate`
  - `GET /v1/blame/{node_id}`, `GET /v1/impact/{node_id}`
  - `GET /v1/graph`, `GET /v1/stats`
- Tenant identity comes only from the bearer token resolved against the registry graph
  (`ped:registry`, Tenant nodes). Request bodies use strict Pydantic models
  (`extra="forbid"`), so a `tenant` field is always rejected.
- Registry tokens are `ped_<tenant>_<32 urlsafe>`; only their sha256 is stored. A 30 s
  in-process cache is explicitly invalidated on create/revoke.
- Correlation id, 256KiB body cap, and a per-tenant rate bucket (120 req/min; revoke 10/min)
  are middleware/dependency driven.
- `PedigreeError` derivatives map to their documented HTTP statuses through a single handler;
  `not_in_graph` always returns 404.
- `pedigree serve` runs `pedigree.api.app:app` via uvicorn.

## Invariants
- Engine is untouched; all paths use `graph_name(tenant)`.
- Auth is required for every `/v1/*` route; health/metrics are public.
- Quota: writes are refused (`quota_exceeded`) when the tenant graph exceeds node_cap.

## Evidence needed
- pytest `tests/integration/test_api.py` green; smoke log of the demo flow.