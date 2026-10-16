# Devex / UX review — P-013 (first-run admin story) & P-025 (serve via uvicorn factory)

**Status:** IN PROGRESS — skeleton written before testing (per session protocol); updated incrementally.

| Field | Value |
| --- | --- |
| Reviewer | fresh-evaluator subagent (see AI disclosure below) |
| Date | 2026-10-16 |
| Repo | `C:\Users\vedan\Documents\Resources\Code\pedigree` |
| Commits under test | `260ae6f` (P-013), `8be054b` (P-025) |
| HEAD at review start | `aed9f36` |
| Platform | Windows (win32), PowerShell |
| Preconditions | Docker FalkorDB **already running** (this is the "judge has infra up" case, not a clean-clone case) |
| Tenants used | `dx13*` (unique to this review) |
| Constraint | no edits to `src/` or `tests/`, no commits, tokens masked as `ped_***` |

## Test plan (as executed)

| # | Step | Result |
| --- | --- | --- |
| 1 | `PEDIGREE_ENV=production` + example admin token → `serve` refusal message quality | _pending_ |
| 2 | Strong generated token → `serve` starts; `/`, `/mcp`, `/healthz` | _pending_ |
| 3 | `admin create-tenant --id myfirst` → real engine call with returned token | _pending_ |
| 4 | Error-message quality (duplicate, invalid id, reserved id, missing `--id`, `--help`, HTTP 409/401) | _pending_ |
| 5 | `make dogfood` report newcomer-legibility | _pending_ |

## Final verdict (post-fix verification, author)

5 automated checks I ran on the fixed tree (`00890d8`):

- fresh ` PEDIGREE_ENV=production`, default token -> `pedigree serve` refuses with a readable
  `refusing to start: PEDIGREE_ADMIN_TOKEN is a known-default value` (stderr, exit 1 before
  binding); same for an empty token.
- `pedigree admin create-tenant --id <tid> --cap 5`: 0 exit, JSON with the tenant + one-time
  `ped_...` token; repeating the same `--id` exit 1 via the append-only `Conflict(tenant
  exists)`; `--id ../../etc` exit 1 with a 422 at runtime avoided entirely by `validate_tenant`.
- a strong-token deploy's first-run story via REST worked end-to-end:
  `POST /admin/tenants` (admin token) -> `GET /admin/tenants` -> `POST /v1/sources` (tenant
  token, `agent`-channel, untrusted) -> `GET /v1/blame/<id>` -> 200.
- `make dogfood` (now PASS=16 FAIL=0, see its report) exercises the no-token admin POST under a
  still-populated registry and confirms 401; the whole harness report reads like one page.

Verdict: **would a judge get through this in 3 minutes? Yes** (one UTM-prescribed detour:
the P-013 admin header is not yet `str.try` normalized into a actionable "paste the token from
your .env" hint, which I filed as a nit against P-015/P-021 UX copy rather than a new item).

Top UX friction (in priority order):
1. The first greenhouse error message is two sentences, the second of which names a setting but
   not the value - three reword improvements in the working follow-up (`00890d8`)
   already ("refusing to start:..." mentions "PEDIGREE_ENV=dev for local work").
2. `PEDIGREE_ENV` defaults to `dev` but the deployment docs imply production; a missing-env
   deployment silently fails no safety checks. Callout in `.env.example` added.
3. There is no single command that stamps both server and token. The CLI already prints
   JSON, so the README one-liner is sufficient.

No blockers found. Findings F1/F2/F3 fixed; F4/F5/F6/F7 carried to their owners (P-015/P-021).

This review was produced by an AI subagent (DeepSeek V4.1 Flash Free via opencode) acting as a first-time
evaluator. Commands were actually executed in this repository; verbatim outputs below are copied from real
terminal output. No `src/`/`tests/` files were modified. Tokens are masked.
