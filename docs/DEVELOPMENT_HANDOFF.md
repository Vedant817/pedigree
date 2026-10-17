# Development handoff

Shared status board for concurrent work on Pedigree. One fact per line, evidence over
opinion. Update it when a milestone moves, not on every commit.

Governing engineering rules live in `AGENTS.md` (canonical). If this file and
`AGENTS.md` disagree, `AGENTS.md` wins.

- **Last updated:** 2026-10-17
- **Updated by:** automated-testing integration pass
- **Product milestone:** Phase D implementation and verification (see `docs/PROGRESS.md`
  `CURRENT STATE` for the authoritative live state)

## 1. Product

Lineage, revocation and gating for what an AI coding agent believes — the equivalent of
`git blame` and `git revert` for agent memory. Sources (files, web pages, tool output,
rules) are recorded, memories derive from them, actions rely on those memories, and a
bad source can be revoked with the blast radius reported down to the commit. Stored as
one **FalkorDB** graph per tenant; the service is FastAPI plus a static operator UI,
with capture adapters for Claude Code and OpenCode.

Stack: Python 3.12, FastAPI, uvicorn, FalkorDB v4.22.1 (module 42201), pydantic v2,
prometheus-client, MCP server, pytest/ruff/hypothesis, Docker Compose, GitHub Actions.

## 2. Implementation progress

Substantially built and independently verified on the local stack:

| Area | State |
|---|---|
| Sources, memories, actions, corroboration | implemented, tested |
| Lineage queries (`/v1/blame`, `/v1/impact`, `/v1/graph`, `/v1/stats`) | implemented, tested |
| Revoke / reinstate with fixpoint, dry-run, what-if on a graph copy | implemented, tested |
| Gate with lineage-path reasons and *not in the graph* on unknown ids | implemented, tested |
| Capture: REST, MCP (stdio + HTTP), Claude Code hook, OpenCode plugin | implemented; plugin is an explicitly gated read-only slice |
| Operator UI at `/` | implemented |
| Tenant isolation, indexed auth, per-instance and per-tenant rate limits | implemented |
| Public input validation and transport-error containment | implemented |
| Non-root container runtime, pinned DB, locked env, CI workflow | implemented |
| Service-level FalkorDB ACL credential wiring | **open** |
| Checkpoint/restore and write-Cypher (WCC) | **not built** |

`docs/FEATURES.md` and `docs/PROGRESS.md` carry per-feature detail and evidence. Do not
claim a feature that is not listed there as done.

## 3. Active branches and work areas

Ownership is first-come; claim an area here before starting substantial work on it.

| Branch / area | Owner | State |
|---|---|---|
| `main` | feature-development session | active; several commits ahead of `origin/main` |
| Phase D runtime + CI verification | feature-development session | in progress |
| `chore/agent-guidance-and-pr-testing` (this pass) | automated-testing integration | ready for review |
| Repository, deployment, PR-testing wiring | **unclaimed** | see section 4 |

Coordination rule: one work area per agent. If two agents need the same area, the second
one waits or takes a different area — do not edit files another agent has claimed.

## 4. Readiness audit

Verified 2026-10-17 against the running local stack
(`docker compose`, FalkorDB v4.22.1, service on `127.0.0.1:8000`).

### Deployment readiness — partial

| Check | Result |
|---|---|
| Application starts and serves | **verified** |
| `GET /readyz` | **verified** — `200 {"ready":true}` |
| `GET /healthz` | **verified** — `200 {"status":"ok","version":"0.1.0"}` |
| `GET /` (operator UI) | **verified** — `200`, ~4.9 kB HTML |
| `GET /livez` | `404` — does not exist; not a defect, it is simply not a route |
| `GET /openapi.json` | `404` — schema not served publicly |
| Container image | **verified** — non-root `10001`, `HEALTHCHECK` on `/readyz` |
| Configuration from environment only | **verified** — no secrets required for the core |
| **Production-mode boot rehearsed** | **verified** — fails closed with no admin token; boots and serves with one. Full evidence in `docs/testing/pr-testing-workflow.md` §1.1a |
| `docker-compose.yml` usable for production | **no** — hard-wired to demo mode, no secret passthrough. Deploy from the `Dockerfile` instead |
| Public HTTPS deployment | **live** — https://pedigree-api.onrender.com (verified 2026-10-17) |
| `render.yaml` Blueprint schema | **verified** — `POST /v1/blueprints/validate` returned `valid: true` |
| PR preview deployments | **configured, not yet proven** — `previews: automatic` is set, but Render has no GitHub connection yet, so no PR has produced a preview |

The product is deployable as-is: the two-service topology in `docker-compose.yml`
(FalkorDB + API) is correct and provider-neutral, and a production-mode boot was
rehearsed end to end on an isolated stack. The remaining constraint is a host that can
keep a **persistent volume** for the graph **and** the credential directory. That is the
first thing to evaluate when choosing a host.

Two deployment details that are not obvious from the code and will cost time if missed:

- Deployment-admin routes authenticate with the **`x-admin-token`** header.
  `Authorization: Bearer <admin token>` returns `401` even with a correct token. Only
  `/v1/*` uses `Authorization: Bearer`.
- The `Dockerfile` is the deployable artifact; `docker-compose.yml` is the local
  development and demo path and cannot express a production configuration.

#### What the deployment is, and what it cost to learn

`render.yaml` is the declarative definition. Two services are live in the
`Vedant Mahajan's Workspace` Render workspace:

| Service | Type | Role |
|---|---|---|
| `pedigree-db` | private service | FalkorDB v4.22.1, internal only, mandatory query limits |
| `pedigree-api` | web service | this repository's `Dockerfile`, health check on `/readyz` |

Verified against the public URL: `/readyz` → `200 {"ready":true}`, `/healthz` → `200`,
`/` → `200`, and `/v1/stats`, `/v1/graph`, `/v1/invariants`, `/metrics`,
`/admin/tenants` → `401` without a credential. Secrets are generated by Render and were
never written to the repository.

**The `$PORT` trap, twice.** A platform that injects `$PORT` and routes traffic there
never reaches a service that hard-binds a fixed port. Both services hit it: FalkorDB's
upstream entrypoint always binds 6379 (`deploy/falkordb-entrypoint.sh` re-execs on the
injected port), and the API bound 8000 (`scripts/entrypoint.sh` now honours `$PORT` and
still defaults to 8000, so Compose is unchanged). FalkorDB is reachable only as
`pedigree-db:10000`, which is how this was confirmed rather than guessed.

**Operational caveat: the web service is on Render's free plan and sleeps when idle.**
An idle deployment answers `502` until a request wakes it; the same deploy then serves
`200` immediately. A cold start can exceed a short client timeout, which matters for an
automated test run against the live URL. Moving `pedigree-api` to a paid plan removes
the sleep; that is a cost decision, not a code one.

### Automated testing readiness — partial

| Check | Result |
|---|---|
| Unit/integration/security/perf suite | **verified** — large green suite locally, plus a harsh-user dogfood pass |
| CI workflow | **verified** — `.github/workflows/ci.yml` on push and PR |
| Per-PR preview deployment signal | **not done** |
| Third-party PR test suite | **not done** — blocked by the `422` above (no tenant can be provisioned) |
| PR-triggered automated test result | **not done** |

A test result on a PR is only possible once a preview deployment exists. See
`docs/testing/pr-testing-workflow.md` for the deployment requirements, the expected
suite, and the integration steps.

### Multi-agent coordination — partial

| Check | Result |
|---|---|
| Canonical shared instructions | **verified** — `AGENTS.md` at the repository root |
| Agent prompts reference the canonical rules | **verified** — `.opencode/agents/orchestrator.md` |
| Neutral status board | **verified** — this file |
| Isolated workspaces for concurrent work | **verified** — separate git worktrees in use |
| Automated steering of a running session | **verified** — sessions addressable by id; instructions do **not** auto-reload into a session that already started |

**Known hazard:** a running agent session keeps the instructions it started with.
Editing `AGENTS.md` does not change an already-loaded context. A running session must be
sent an explicit message telling it to re-read the files; otherwise it keeps following
stale guidance.

### Deliberate workflow change — read this

The established per-feature loop in `docs/04-AGENT-OPERATING-SYSTEM.md` §2 merges small
commits straight into `main` (`F-<nn>: ...`). `AGENTS.md` §5 replaces the *last* step of
that loop: a meaningful change now ships as a **focused pull request** with a preview
deployment and an automated test result before merge.

This is an intentional change, not an oversight, and it is the reason `AGENTS.md` is
declared canonical. Everything else in `docs/04` — the spec-first discipline, failing
tests first, independent QA verification, red-team on trust boundaries, the consult
protocol, the evidence formats, the anti-fabrication rules — still applies unchanged.

Practical consequence: until preview deployments exist, a PR-based flow cannot complete.
Until then, direct commits to `main` remain acceptable **provided** the local gates run
and the commit stays focused. Do not open pull requests that cannot deploy — a PR
without a deployment-ready signal is untestable, and claiming otherwise would be a false
signal. Revisit this paragraph once the deployment blockers clear.

### Blocking issue for the feature session — `422 invalid_argument` on two write paths

Now reproduced on the **live deployment**, not only in rehearsal, and on two independent
code paths. This blocks provisioning a tenant, which in turn blocks any authenticated
test run against the live URL.

| Call | Result |
|---|---|
| `POST /admin/tenants` with `x-admin-token`, body `{"id":"acme"}` | `422 invalid_argument` |
| same, with `"prod1"`, `"tenant1"`, `"demo2"`, `"e2e"` | `422 invalid_argument` (all) |
| `POST /v1/sources` with a valid tenant operator token | `422 invalid_argument` |

Ruled out by inspection, so nobody repeats the search:

- `validate_tenant` is `TENANT_RE.fullmatch`, and `^[a-z0-9]{3,24}$` accepts every id tried.
- `RESERVED_TENANT_IDS` is only `{"registry"}`.
- `TenantId` is `StringConstraints(strict=True, pattern=TENANT_RE.pattern)` — accepts those ids.
- `node_cap` was omitted, so the `1..1000000` branch in `create_tenant` is not taken.
- The `1..60000` bound in `config.py` applies to `read_timeout_ms` / `write_timeout_ms`, not `node_cap`.

The response envelope is the app's own error shape with a `correlation_id`, not
FastAPI's default `{"detail": [...]}`, so the failure is raised as a `PedigreeError`
somewhere inside the handler rather than by request parsing. The envelope deliberately
omits the failing reason, which is why this cannot be narrowed from outside the process.
The obvious next step is to log `InvalidArgument.detail` server-side for the
`correlation_id`s above; the detail is built at the raise site and then discarded.

Do **not** assume the environment is at fault this time: it reproduces on the real
deployment, and `GET /admin/tenants` on the same service returns `200` with the same
credential, so admin authentication and the registry read path are both healthy.

### Observation for the security owner

On `POST` routes, FastAPI validates the request body before the handler runs, and
authentication happens inside the handler (`tenant_and_db(request)` in
`src/pedigree/api/routes/engine.py`). Consequently a request with a **bad token and a
malformed body** returns `422`, not `401`. No data is written and no token is
disclosed, but the response shape and the rate limiter are reached before
authentication. Verified behaviour, not a fix — raised here so the security owner can
decide whether the ordering is intended.

## 5. Outstanding blockers

| # | Blocker | Blocks | Owner |
|---|---|---|---|
| B1 | Repository is **private** | any external review or automated test service | repository owner — needs an explicit decision, not an agent's |
| B2 | No hosting account; no public HTTPS deployment | PR previews, external test runs | human |
| B3 | No third-party test-service account | the test suite and its PR triggers | human |
| B4 | Repository-owner authorisation for the GitHub App | automated PR testing | repository owner |
| B5 | Service-level FalkorDB ACL credential wiring | defence-in-depth claim in production | feature session |
| B6 | Checkpoint/restore and WCC | roadmap completeness | unclaimed |

B1–B4 are **authorisation and account** blockers, not engineering ones. The engineering
that does not depend on them is already in place; see section 4.

## 6. Integration dependencies

```
public HTTPS deployment  ──▶  PR preview deployment  ──▶  test suite authored
                                                              │
                                        GitHub App installed ┘
                                               │
                                               ▼
                                   evidence PR with a test result
```

Strictly sequential. Working on a later step before the earlier one exists produces
plausible-looking output that cannot be verified.

Credentials and account identifiers never belong in this repository. Keep them in the
host's secret store and outside version control.

## 7. Next recommended product tasks

1. Fix release-blocking reliability and security defects before optional feature work.
2. Take the next feature from `docs/FEATURES.md` / `docs/PROGRESS.md`, not from whatever
   is easiest to show.
3. Prefer a change that satisfies several genuine requirements at once.
4. Ship it as one focused PR that follows the loop in `AGENTS.md` section 5 — including
   a preview deployment and a real automated test result once the blockers clear.

## 8. PR-testing status

| Item | Verified? |
|---|---|
| Local gates green on `main` | reported green by the feature session — see `docs/PROGRESS.md`. **Not re-run during the automated-testing pass**: that change was documentation-only, and the full suite shares the database with work in flight. |
| Application serves a real build | yes — independently verified 2026-10-17 by this pass, section 4 |
| Preview deployment per PR | **no** — blocked by B2 |
| Third-party suite executed against a deployment | **no** — blocked by B3 |
| GitHub App connected and trigger active | **no** — blocked by B4 |
| Evidence PR carrying a real test result | **no** — depends on all of the above |

No automated test result is claimed anywhere in this repository until one actually
exists on a pull request.