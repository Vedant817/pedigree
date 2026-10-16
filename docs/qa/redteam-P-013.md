# Red-team: P-013 - admin auth fail-closed

- Commit under test: `260ae6f` (P-013: admin auth fail-closed - constant-time compare, startup guard, admin create-tenant CLI)
- Repo: `C:\Users\vedan\Documents\Resources\Code\pedigree`
- Date: 2026-10-16
- Scope: admin auth surface (`api/routes/admin.py`, `api/app.py` startup guard, `cli.py admin create-tenant`), interaction with `/metrics` and tenant routes.
- Rules: local instance only; test tenants prefixed `rt13`; tokens masked to first 10 chars; no edits to `src/`/`tests/` other than the adversarial test added under `tests/security/`; no commits.
- Scratch dir: `%TEMP%\opencode\rt13\`
- Test added: `tests/security/test_redteam_p013_adv.py` (currently 5 failing, 1 passing; see below).

## Summary verdict

Admin auth is fail-closed on the direct path (constant-time compare, no `has_tenants()` bypass), startup guard works for HTTP `serve`, and cross-tenant access via the admin header was **not** reproduced. Findings are input-validation and usability/consistency gaps, not an auth bypass:

- Tenant ids accepted by the admin path are validated against the permissive `ID_RE`, not the `TENANT_RE` choke point used for graph names.
- `node_cap` has no bounds (including `0`, negatives, and huge values).
- Header whitespace is not canonicalized even though the config guard canonicalizes the configured token.
- The admin token is also the global operator credential (trusted-source minting) with no separate scope.
- Startup guard is only enforced by the HTTP factory; the standalone MCP server starts with an empty admin token.

## Attacks tried (>= 10) and results

| # | Attack | Result |
|---|---|---|
| 1 | `has_tenants()` monkeypatch to False, then POST/GET `/admin/tenants` | 401 both; no bootstrap bypass (confirmed no `has_tenants()` call site in routes except definition/tests) |
| 2 | Header name case variants (`x-admin-token`, `X-ADMIN-TOKEN`, `X-Admin-Token`) | 200 only with correct value; 401 otherwise (Starlette case-insensitive, as expected) |
| 3 | Missing / empty / wrong admin header | 401 in all cases |
| 4 | Correct token without header | 401 |
| 5 | Correct token with trailing/leading whitespace in header | 401 (correctly rejected) |
| 6 | Duplicate `X-Admin-Token` headers (first-wrong/second-correct and reverse) | first-wins; 200 only when first is correct. No bypass because the attacker cannot know the configured token. |
| 7 | Tab/null bytes inside header value | 401 |
| 8 | Oversized admin header (1 KB / 64 KB / 1 MB) | 401 without measurable delay; compare_digest handles length mismatch |
| 9 | Wrong/revoked tenant bearer token combined with admin header | admin endpoints still require admin header; tenant identity stays bound to bearer token |
| 10 | Tenant token reused as `X-Admin-Token` | 401 (not a valid admin token) |
| 11 | HTTP `/admin/tenants` create with invalid tenant id (`../../etc`, `ped:abcd`) | 200 (accepted - finding) |
| 12 | `--cap 0`, negative, huge values via CLI | accepted (finding) |
| 13 | `.env` vs shell env precedence for `PEDIGREE_ADMIN_TOKEN` | shell env wins (expected pydantic precedence) |
| 14 | Startup with production + empty/default admin token | raises RuntimeError (guard works) |
| 15 | `/metrics` unauthenticated | 200, Prometheus metrics (no admin secret in output); informational |
| 16 | Error-message scan for admin token leakage | messages use `admin token required` / guard problem text; no token echoed in tested paths |
| 17 | CLI `create-tenant --id` validation | no tenant-id regex enforced (finding) |
| 18 | Concurrent `create_tenant` (8 threads, same id) | one success, rest 409 `tenant exists`; no clobber observed |
| 19 | `get_settings()` caching after env change | cached (expected, not security-relevant in a single process) |

## Findings

### Finding F1 - Admin path validates tenant ids with `ID_RE`, not `TENANT_RE`
- Repro: `POST /admin/tenants` with `{"id": "../../etc"}` or `{"id": "ped:abcd"}` behind a valid admin token returns 200 and inserts a registry row whose id can never produce a valid graph name (`graph_name` raises `InvalidArgument` later). CLI equivalent: `pedigree admin create-tenant --id ../../etc` exits 0.
- Severity: Medium (input validation, registry pollution, inconsistency with the graph-name choke point; no direct auth bypass since the resulting tenant is unusable, but it does violate the documented tenant-id contract and the cross-tenant graph-name protections).
- Fix: make `TenantCreate.id` use `constr(pattern=TENANT_RE.pattern)` (or equivalent), call `validate_tenant()` instead of `validate_id()` in `TenantRegistry.create_tenant`, and validate `--id` in the CLI/admin path. Existing rows can be left; new creation must fail closed.
- Test id: `test_admin_create_rejects_invalid_tenant_id`, `test_admin_create_rejects_graph_name_trick_id`, `test_cli_rejects_invalid_tenant_id` (in `tests/security/test_redteam_p013_adv.py`).

### Finding F2 - `node_cap` is unbounded and treats `0` as "unset"
- Repro: `POST /admin/tenants` with `node_cap: -1` returns 200; `node_cap: 10**12` returns 200; CLI `--cap 0` silently substitutes the default cap instead of rejecting.
- Severity: Medium (quota evasion / invalid configuration injected by anyone holding the admin token; a negative cap can also make every tenant instantly quota-exhausted).
- Fix: validate in Pydantic (`Field(ge=1, le=<max>)`, and in CLI (`--cap` with type and bounds), drop the `or` coercion so an explicit `0`/negative is rejected rather than replaced.
- Test id: `test_admin_create_bounds_node_cap`, `test_cli_rejects_zero_cap`.

### Finding F3 - Header whitespace is not canonicalized, although the configured token is
- Repro: configure `PEDIGREE_ADMIN_TOKEN="  test-admin-strong-9f2c4e  "` and present `X-Admin-Token: test-admin-strong-9f2c4e`; result is 401. `admin_token_problem()` strips the configured token before deciding usability, but `_require_admin()` and `operator_authorized()` compare the raw configured value.
- Severity: Low (availability/usability; not a bypass, because the strict comparison only ever rejects more. Combined with copy/paste of secrets, though, it pushes operators toward weaker tokens or disabling guards).
- Fix: apply `.strip()` consistently in `_require_admin()` and `operator_authorized()` (and CLI) when materializing `expected`, matching `admin_token_problem()`.
- Test id: `test_admin_header_whitespace_normalized`.

### Finding F4 - One admin token is also the global operator credential (no role separation)
- Repro: the same `X-Admin-Token` value gates `/admin/*`, `/v1/admin/resume`, and all trusted-source/integrity/`by=human|scanner` operations across every tenant. There is no distinct operator credential or per-tenant scoping; any holder of the admin token can mint `integrity=trusted` sources and assert trusted corroboration in any tenant.
- Severity: Medium (over-broad privilege; a leaked admin token compromises integrity attestation for all tenants, not just admin-plane actions).
- Fix: introduce a separate `pedigree_operator_token` (or scope the existing one per tenant) and have `operator_authorized()` check that distinct credential; keep `X-Admin-Token` for admin-plane routes only.
- Test id: (no failing test added - architecture only; proposed as a design change in consultation).

### Finding F5 - Startup guard is HTTP-only; standalone MCP server starts with an empty/known-default admin token
- Repro: `pedigree mcp ...` calls `build_mcp()` directly and never invokes `admin_token_problem()`; only `create_app()` (used by `serve`) refuses to start. In deployments that run the MCP server directly (or embed it), an empty or known-default admin token is accepted.
- Severity: Medium (the guard's contract ("refusing to start") is not universal across entry points; `/admin` HTTP routes are not mounted in MCP-only mode, but `operator_authorized` stays disabled/True? It stays False for empty, so trusted minting stays off - no bypass of HTTP routes, but silent allowance).
- Fix: call `admin_token_problem(settings)` (and refuse) in `PedigreeMCPServer.__init__` / `build_mcp`, or in the `mcp` CLI branch, consistent with `serve`.
- Test id: (no failing test added - requires a process-level MCP test; proposed).

### Finding F6 - Generic exception handler echoes `str(exc)` to clients
- Repro: any unhandled exception is returned to the HTTP client as `{"message": str(exc)}` via `_register_error_handlers`. FalkorDB/registry errors can include connection/auth details in some paths, and there is no last-line redaction of the configured admin token anyway, but the channel is broad.
- Severity: Low (information-disclosure hardening; no observed admin-token leak in the tested paths because `Unauthorized("admin token required")` carries no secret).
- Fix: replace `str(exc)` in the generic handler with a generic message (keep the secret behind a correlation id / server log), and never log the admin token.
- Test id: (no failing test added - defensive hardening).

### Finding F7 - Default environment is `dev`, so a stock deployment with an empty/known-default admin token starts without ceremony
- Repro: `Settings()` default `pedigree_env="dev"` (and `.env.example` ships `PEDIGREE_ENV=dev` + `PEDIGREE_ADMIN_TOKEN=change-me-admin`), so `admin_token_problem()` returns `None` and startup succeeds even though the admin token is empty or a well-known string. A production deployment that forgets to change `PEDIGREE_ENV` keeps a guessable admin token.
- Severity: Medium (insecure default / foot-gun; production safety depends entirely on the operator remembering to set `PEDIGREE_ENV=production`).
- Fix: change the default to a non-dev value that fails closed, or remove the "dev default" fallback and require an explicit `PEDIGREE_ENV=dev|local` opt-in; document loudly. (Note: broad test impact; propose in consultation, not applied here.)
- Test id: (no failing test added - would break the devex/local flow and many tests by design).

## Non-findings (confirmed)

- No `has_tenants()` call site in routes/admin paths; bootstrap bypass eliminated at construction.
- Constant-time compare is used (`hmac.compare_digest`) for admin and operator checks.
- Header case handling is case-insensitive with no bypass; duplicate headers are first-wins with no injection vector for unknown tokens.
- Oversized headers do not cause a measurable DoS in-process.
- Tenant identity is bound to the bearer token (`auth.authenticate`), so the admin header cannot switch tenants.
- `create_tenant` check-then-act race does not clobber an existing tenant (verified with 8 threads).

## Post-report follow-up (2026-10-16, commit `00890d8`)

The Medium/Low findings below were addressed **in-code** after this adversarial report landed:
- **F1 (Medium):** tenant ids now validated against `TENANT_RE` (`validate_tenant` in
  `TenantRegistry.create_tenant`), so `../../etc`, `ped:abcd`, and other non-graph-safe ids
  return `invalid_argument` 422 instead of creating unusable registry rows.
- **F2 (Medium):** `node_cap` bounded in `[1, 1_000_000]`; explicit `0`/negative now raises
  instead of silently substituting the default.
- **F3 (Low):** admin header + operator checks `strip()` the expected/presented values
  consistently with `admin_token_problem()`.
- F4 (role separation), F5 (HTTP-only guard), F6 (generic handler str(exc)), F7 (dev default
  env) are deliberately carried to their owning audit items: P-015 and P-021.

Regression: `tests/security/test_redteam_p013_adv.py` moved from 5-failing/1-passing to **6/6
passing** as of `00890d8`, alongside the original `tests/security/test_admin_auth.py` (6
passed) and the full gate (430 passed, 1 skipped, 3 deselected, 1 xfailed).
- Test tenants created by the new adversarial test are scheduled for cleanup inside the test (`_cleanup`); invalid-id rows are attempted via a direct registry `DELETE` (graph-name variants are skipped because they never had a graph).
- No `src/` or existing `tests/` files modified; no commits made.
- Scratch artifacts remain under `%TEMP%\opencode\rt13\`.
