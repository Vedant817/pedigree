# Development handoff

- **Active work area:** tenant database ACL service wiring; branch `feat/tenant-db-acl-20261018`. Dedicated isolated test DB only; no checkpoint or spool edits.

Shared status board for concurrent work on Pedigree. One fact per line, evidence over
opinion. Update it when a milestone moves, not on every commit.

Governing engineering rules live in `AGENTS.md` (canonical). If this file and
`AGENTS.md` disagree, `AGENTS.md` wins.

- **Last updated:** 2026-10-17
- **Updated by:** feature-development session (Phase F: P-017 capture landed, QA follow-up fixed, full `make check` green)
- **Product milestone:** Phase F in progress. P-017 synthetic web and shell-read capture
  is on `main` through `097309d`. Devex QA on the first capture commit passed;
  correctness and red-team failed that commit, and the code bugs they named are
  fixed in `097309d` without a new QA report yet. P-023 independent QA closure is
  still open. Installed Claude capture, disclosure voice, video, and publish stay
  human-only. See `docs/PROGRESS.md` `CURRENT STATE` for the authoritative live state.

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
| Phase D runtime + CI verification | feature-development session | **done** — `docs/qa/P-003.md` (PASS with caveats), `docs/qa/P-028.md` (PASS), `docs/qa/redteam-P-003.md` (PASS); findings in `docs/KNOWN_ISSUES.md` |
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
| Per-PR preview deployment signal | **not done** — `previews: automatic` is configured; no GitHub connection yet |
| Third-party PR test suite | **unblocked** 2026-10-17 (see the resolved 422 note); execution still needs the preview deployment and the connected triggers (B2/B4) |
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

### Resolved 2026-10-17 — `422 invalid_argument` on write paths

Reproduced locally on production-mode code with a real FalkorDB, root-caused, and
closed by the feature session. The API was not rejecting valid provisioning requests:
it was rejecting bodies that are not valid JSON for the declared model, and the
detail-free public envelope made every 422 look identical.

| Call | Result |
|---|---|
| `POST /admin/tenants`, `Content-Type: application/json`, body `{"id":"acme"}`, `x-admin-token` | `200` — tenant created, agent + operator credentials returned |
| same body sent form-encoded (curl `-d` / PowerShell `-Body` default) | `422 invalid_argument` |
| same, with an unknown field (e.g. `"tenant"`) | `422 invalid_argument` |
| `POST /v1/sources` with a valid operator bearer, clean JSON body | `200` |
| `POST /v1/sources` with an unknown field or a non-JSON body | `422 invalid_argument` |
| `POST /admin/tenants`, correct JSON, no admin header | `401` (auth still precedes the handler) |

Reproduction: `scratch/repro422.py` (local, production settings, real FalkorDB),
2026-10-17. The earlier "raised inside the handler" inference was wrong: the
`RequestValidationError` handler produces the same envelope shape as a typed error —
the distinguishing key is that a typed error carries `error.detail`. Two fixes landed
with this closure:

- request-validation failures are logged server-side with the correlation id, field
  path and error type — never the submitted value or the validator message;
- authored `invalid_argument` rejections log their static reason and the
  identifier-shaped `detail` keys only.

The exact request the live deployment received was not captured, so re-verify the
live call with the deployment's admin token before relying on it:

```bash
curl -sS -X POST https://pedigree-api.onrender.com/admin/tenants \
  -H "Content-Type: application/json" \
  -H "x-admin-token: $PEDIGREE_ADMIN_TOKEN" \
  -d '{"id":"acme"}'
```

### Observation for the security owner

On `POST` routes, FastAPI validates the request body before the handler runs, and
authentication happens inside the handler (`tenant_and_db(request)` in
`src/pedigree/api/routes/engine.py`). Consequently a request with a **bad token and a
malformed body** returns `422`, not `401`. No data is written and no token is
disclosed, but the response shape and the rate limiter are reached before
authentication. Verified behaviour, not a fix. Decision recorded 2026-10-17: keep the
ordering (the exposure is a schema shape, not data, and no state change is possible);
the accepted limitation is in `docs/KNOWN_ISSUES.md` (P-003 QA F1 / redteam-P-003 F2).

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
| Local gates green on `main` | green — feature session root `make check` 2026-10-17 on the verification-closure tree: 809 passed, 2 skipped, 4 deselected, 1 xfailed (165.02s); Ruff, tracked secret scan and `check_numbers` PASS. Log: `scratch/make-check-phase-d-verification.log` |
| Application serves a real build | yes — independently verified 2026-10-17 by this pass, section 4 |
| Preview deployment per PR | **no** — blocked by B2 |
| Third-party suite executed against a deployment | **no** — blocked by B3 |
| GitHub App connected and trigger active | **no** — blocked by B4 |
| Evidence PR carrying a real test result | **no** — depends on all of the above |

No automated test result is claimed anywhere in this repository until one actually
exists on a pull request.
## Release completion 2026-10-18
- release/production-completion-20261018: Codex orchestrator owns production readiness, recovery and integration. Existing main worktree edits preserved. Real release-test DB uses port 6381; old crashed volume preserved.

