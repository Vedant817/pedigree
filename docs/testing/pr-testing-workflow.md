# Automated pull-request testing

Pedigree uses **TestSprite**, a third-party automated testing service, to exercise a
deployed build of this service every time a pull request opens. TestSprite does not
build or deploy Pedigree. It listens for the deployment event GitHub already reports,
resolves the preview URL, runs its suite against that URL, and posts the result back on
the PR as a `testsprite-dev` comment (PR trigger) or a status check (push trigger).

Official setup docs: <https://docs.testsprite.com/web-portal/integrations/github-integration>

This document is the engineering side of that integration: what must exist before it
works, the suite we expect, and how an agent uses the results honestly.

## 1. What has to be true before any test can run

TestSprite has nothing to hit until two things exist. Both are prerequisites, not
nice-to-haves.

### 1.1 A public HTTPS deployment

| Requirement | Value |
|---|---|
| Protocol | HTTPS, publicly resolvable |
| Reachability | any external client, no VPN, no localhost, no tunnel that requires an account |
| Startup | must come up from a cold start with configuration supplied as environment variables |
| Data store | reachable from the deployment |

Pedigree is **not** a single-process app: the API (`src/pedigree/api`) needs a running
**FalkorDB v4.22.1** (module `42201`) and persists state on a volume. A deployment
therefore has two services, not one:

- `db` — `falkordb/falkordb:v4.22.1`, the pinned image already used by
  `docker-compose.yml` and CI, with the same mandatory limits
  (`TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`).
- `api` — the existing `Dockerfile` (already non-root `10001`, already has a
  `HEALTHCHECK` on `/readyz`, already reads configuration from the environment).

`docker-compose.yml` is already the correct two-service topology, so a host that can run
a Compose/Dockerfile pair needs no architectural change. What a host cannot do is
provide a stable persistent volume for both the graph and the credential directory —
that is the constraint to evaluate first when choosing a provider.

Required configuration (see `.env.example`); nothing else is needed for the core:

```
PEDIGREE_ENV=production     # enables the admin-token guard; dev/test/local do not
PEDIGREE_ADMIN_TOKEN=...    # non-default value required outside dev/test/local
PEDIGREE_SECRET=...         # HMAC key for content fingerprints
PEDIGREE_DB_ACL=false       # unless the DB grants per-tenant ACL users
FALKOR_HOST / FALKOR_PORT
PEDIGREE_PUBLIC_URL=https://...   # must match the real public origin
```

**Secrets belong in the host's secret store**, never in the repository. `.env` is
git-ignored and `scripts/secret_scan.py` runs in `make check`; that guard must stay
green.

The smallest authentic public interface is the existing product: `/` (workspace UI),
`/healthz`, `/readyz`, and the `/v1/*` API. Do not add a marketing front end or a
synthetic demo page that is not wired to real engine behaviour.

### 1.2 A preview deployment per pull request

Every PR needs its **own** deployment of its own commit, and GitHub must report that
the deployment is ready. TestSprite's `Detect Events` lists the checks, workflow runs and
bot comments it can see on a PR; it needs one of them to mean *"this build is deployed
and reachable"*.

Acceptance test for this prerequisite — all four must hold:

1. A GitHub deployment status exists for the PR head commit.
2. A named check or workflow run reports the deployment as **ready** (not merely
   "build started").
3. The preview URL serves the PR's code, not `main`'s.
4. Opening that URL returns a working Pedigree (`/readyz` → `{"ready":true}`).

If none of those hold, fix the pipeline first. Opening a PR is not a deployment.

## 2. Test suite

The suite is authored in the TestSprite portal against the live URL. Design rules:

- **Assert behaviour, not the absence of an error.** `GET /readyz` returning 200 is
  worth one scenario; it is not worth ten.
- **Use a dedicated tenant with disposable data.** Scenarios create sources, memories
  and actions; they must never mutate seeded demo or production data. Reuse one
  throwaway tenant id per run and let quota/isolation handle the rest.
- **Never point destructive scenarios at real user data.** Revoke and reinstate scenarios
  belong on the disposable tenant only.
- Prefer end-to-end journeys that a real operator would perform, over isolated endpoint
  pokes.

### 2.1 Expected coverage

Scenarios below are grouped by the behaviour they defend. Field names and status values
are taken from `src/pedigree/api/schemas.py`, `src/pedigree/api/routes/` and
`src/pedigree/engine/`, so they match the shipped contract.

**Availability and health**
1. `GET /` loads the workspace UI and shows the tenant/paste-token affordance.
2. `GET /readyz` → `{"ready": true}`; `GET /healthz` → status `ok` with a version.
3. An unknown path returns a 4xx, not a stack trace.

**Authentication and authorisation** (the trust boundaries; highest value)
4. `GET /v1/stats`, `/v1/graph`, `/v1/invariants`, `/v1/audit/sources` with **no**
   `Authorization` header → `401`.
5. The same routes with an unknown bearer → `401`.
6. A malformed `Authorization` header (no `Bearer ` prefix, double space, embedded
   whitespace, empty token) → `401`, never `200`.
7. `GET /metrics` without the admin credential → not `200`.
8. A tenant token for tenant **A** cannot read or mutate tenant **B**'s graph — ids,
   sources and actions stay scoped. This is the single most important scenario in the
   suite.
9. A tenant-scoped credential that attempts an operator-only action
   (`integrity: "trusted"`, or corroboration `by: "human"`) → `403`, and the node is
   not created.

**Core workflow** (capture → memory → action → query)
10. `POST /v1/sources` with a disposable id returns `id`, `status`, `low_integrity`,
    `conf_eff`. A source reported by an agent without an operator credential is recorded
    as **untrusted**, not trusted.
11. `POST /v1/memories` referencing that source via `derived_from` records lineage.
12. `POST /v1/actions` with `relied_on` referencing the memory records an action.
13. `GET /v1/blame/{node_id}` returns the ancestor path; `GET /v1/impact/{node_id}`
    returns the descendants the node contaminated.
14. `GET /v1/graph` and `GET /v1/stats` reflect the writes above.

**Revocation — the product's differentiator**
15. `POST /v1/revoke` with `dry_run: true` on a disposable tenant reports the blast
    radius **and changes nothing** — the graph is identical afterwards.
16. `POST /v1/revoke` for real marks the source revoked and its descendants
    contaminated.
17. `POST /v1/reinstate` after the revoke fixpoint: the source is active again, and the
    reinstate **does not** clobber unrelated roots.
18. After a revoke, `POST /v1/gate` on an action that relied on a contaminated
    dependency is **blocked** and the reason names the lineage path.

**Gating**
19. `POST /v1/gate` for an action with no recorded lineage answers **not in the graph**,
    never "safe".
20. `POST /v1/gate` for an action supported only by independently corroborated
    dependencies is **allowed**.

**Input validation and failure paths**
21. Unknown field names are rejected (the request models are strict).
22. An out-of-range `tenant_id` or malformed id → validation error, not a traceback.
23. Missing `Authorization` combined with a malformed body still fails closed.
24. A tenant at its `node_cap` refuses further writes with a clear error instead of
    corrupting the graph.
25. `GET /v1/invariants` reports clean after every scenario group — no orphaned
    `DERIVED_FROM` parents, no cycle.

**Regression-prone multi-step journeys**
26. Full journey: create source → memory → action → read back → `dry_run` revoke →
    real revoke → gate decision → reinstate → re-gate decision. One scenario, one
    assertion chain.
27. A bad actor/tenant id surfaces in the error message and is recoverable without a
    server restart.

### 2.2 Assertions worth trusting

- Assert on **specific fields** (`status`, `low_integrity`, `conf_eff`, gate decision,
  reason text), not on HTTP 200 alone.
- For the gate, assert the decision **and** that the reason names the lineage path — the
  reason is the feature.
- For unknown ids, assert the specific *not in the graph* style response. A generic
  empty success is a defect.
- Never assert on response-time numbers, exact node counts across tenants, or anything
  derived from seeded demo data.

## 3. Wiring the GitHub App

One-time per workspace. **This adds no files to this repository** — the App listens to
GitHub events, so there is nothing to commit and no CI to duplicate.

1. In TestSprite: *Workspace Settings → Connections → Integrations* → **GitHub** →
   **Connect**.
2. Authorize on GitHub. Grant **read** on actions, checks, issues, metadata; **read/write**
   on code, commit statuses, deployments, pull requests. Restrict to this repository
   unless you have a reason not to.
3. Confirm the integration shows **Connected**.
4. Open the project → **GitHub Action** tab → **Add Trigger** → **Pull Request**.
5. Paste a PR URL that has a working preview deployment → **Detect Events**. Pick the
   event that fires *after* the deployment is reachable, not one that fires at build
   start.
6. Set the **Target URL pattern** using placeholders `{pr}`, `{branch}`, `{branch-slug}`,
   `{sha}`, `{short-sha}` so TestSprite can build the preview URL for any future PR.
7. **Send Test Event**, then confirm a real `testsprite-dev` comment appears on the PR
   and updates in place when the run finishes.
8. **Create Trigger**. It shows **Active** and fires on every subsequent PR.

Optional: a **Push to Branch** trigger for a shared environment. Leave *Block PR until
tests pass* **off** until the suite is stable, then turn it on.

## 4. How agents use the results

1. Define acceptance criteria before implementing.
2. Implement the change and its unit/integration tests.
3. Run local gates: `make check`, plus `make check-perf` when traversal, revoke or gate
   changed.
4. Open a focused PR — one concern per PR.
5. Wait for the preview deployment to report ready.
6. Let the trigger fire; do not run the suite by hand to "confirm" it.
7. **Read the actual TestSprite comment on the PR.** Do not infer the outcome from CI.
8. Fix legitimate failures at the cause. Never relax the assertion to get a green PR.
9. Push the fix and confirm the rerun on the PR.
10. Keep the passing PR as regression evidence.

### Anti-fabrication rules for this integration

- Unit tests are **not** evidence that TestSprite ran. Only a real TestSprite result on
  the PR is.
- Never fake, hand-write, or screenshot a result. Never substitute a hand-written
  GitHub Action that prints "tests passed" for TestSprite's own execution.
- Never manufacture a failure to demonstrate the loop.
- If the trigger did not fire, that is a finding to report — not something to paper over
  with a manual run presented as automation.
- If a scenario fails, report it as-is even when it is inconvenient. Unflattering
  results are part of the evidence.

## 5. Current status

| Item | State |
|---|---|
| Service verified locally (health, UI, auth boundaries) | done — see `docs/DEVELOPMENT_HANDOFF.md` |
| Two-service deployment topology | defined (`docker-compose.yml`, `Dockerfile`) |
| Public HTTPS deployment | **not done** — needs a host account and a persistent volume |
| Preview deployment per PR | **not done** — depends on the above |
| TestSprite account / project / suite | **not done** — needs a TestSprite account |
| GitHub App installed | **not done** — needs repository-owner authorisation |
| Evidence PR with a TestSprite result | **not done** — depends on all of the above |

Setup order is strict: deployment → preview → suite → GitHub App → evidence PR. Each
step depends on the one before it.