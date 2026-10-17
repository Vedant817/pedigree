# AGENTS.md — shared engineering instructions (canonical)

This file is the **single source of truth** for how any coding agent works in this
repository. If another instruction file disagrees with this one, this file wins; fix
the other file rather than adding a second policy.

Scope: the whole repository. Role prompts under `.opencode/agents/` are specialisations
of these rules — they add role duties, they do not relax them.

## 0. Read this first

Before planning a substantial feature, changing shared infrastructure, or opening a
pull request, re-read:

1. `AGENTS.md` (this file)
2. `docs/DEVELOPMENT_HANDOFF.md` — current milestone, who owns what, what is blocked
3. `docs/PROGRESS.md` — the `CURRENT STATE` block is the live resume point
4. `docs/DECISIONS.md` — permanent decisions (ADRs); do not relitigate them silently
5. `docs/04-AGENT-OPERATING-SYSTEM.md` — the full per-feature loop and role protocol
6. `docs/02-ARCHITECTURE.md` — before changing schema, tenancy or the trust model

**Do not trust instructions remembered from an earlier session.** Guidance, ownership
and blockers change between sessions. Reading these files costs one tool call; acting
on a stale copy of them costs a rewrite.

## 1. Repository map

| Concern | Location |
|---|---|
| Service (FastAPI), engine, DB access, MCP server | `src/pedigree/` |
| Operator UI (static) | `src/pedigree/ui/` |
| Capture adapters (Claude Code hook, OpenCode plugin) | `adapters/` |
| Tests (unit, integration against real FalkorDB, security, perf, e2e) | `tests/` |
| Feature specs, QA evidence, consults, ADRs | `docs/` |
| Agent role prompts | `.opencode/agents/` |
| Local runtime, CI, deployment | `Makefile`, `docker-compose.yml`, `Dockerfile`, `.github/workflows/` |

Product in one line: lineage, revocation and gating for what an AI coding agent
believes — "git blame and git revert for agent memory", stored as one FalkorDB graph
per tenant.

## 2. Validate before you claim

Smallest gate first; run it once after the focused change, not repeatedly.

```bash
make test-quick      # fast suite (deselects slow and perf)
make check           # ruff + test-quick + secret scan + numbers check  <- pre-commit gate
make check-perf      # heavy real-DB perf gates; only when touching traversal/revoke/gate
make dogfood         # end-to-end harsh-user scenarios against a spawned server
```

A claim needs the command and its real output. Never report a gate that was skipped,
timed out, or that failed before reaching the check it was supposed to run.

## 3. Preserve ongoing work

- Multiple agents work in this repository, in separate sessions and sometimes in the
  same worktree.
- **Run `git status` before every edit, commit, merge or rebase.** If the tree is not
  clean, you do not own those changes — do not commit, stash, discard or "fix" them.
- Never `reset --hard`, `checkout --`, `clean`, force-push, or delete another agent's
  worktree. Those are destructive, not tidy.
- Never rewrite or rebase commits that are already on a shared branch.
- Do not edit another agent's branch or worktree. Take your own branch.
- If you must wait for work in flight, do other work and say so — do not serialise on
  guesswork.
- `git push` to a shared branch is a human-visible action: ask first unless you were
  told otherwise.

## 4. Engineering quality

- Production-quality, maintainable code — not a demo that passes one test.
- Preserve reliability and backward compatibility. Public API and MCP contracts are
  compatibility surfaces; changing them needs an ADR in `docs/DECISIONS.md`.
- Respect the existing architecture: one graph per tenant, tenant derived from the
  bearer token only, static parameterised Cypher, no `MULTI`/`EXEC`, timeouts on every
  query, typed error codes with no stack traces.
- Write the tests the change needs: unit, integration against real FalkorDB, a property
  test where an invariant exists, and at least one failure-injection case.
- Handle meaningful errors and edge cases. Unknown ids must answer *not in the graph*,
  never "safe" and never a silent empty result.
- Prefer minimal, compatible changes. Do not opportunistically refactor code you are
  not already changing.
- Never commit secrets, tokens, real user data or absolute local paths. `.env` stays
  untracked. `scripts/secret_scan.py` must pass.
- Document permanent technical decisions as ADRs; do not leave reasoning only in chat.
- Do not invent URLs, versions, benchmark numbers or third-party claims. Verify, or mark
  the claim unverified.

## 5. Automated pull-request testing

Every meaningful product change ships as a focused pull request and is tested
automatically by **TestSprite**, a third-party automated testing service configured for
this repository. Full setup and the scenario plan: `docs/testing/pr-testing-workflow.md`.

The loop:

1. Define acceptance criteria for the change before implementing it.
2. Implement the functionality **and** its unit/integration tests.
3. Run the local gates (`make check`, plus `make check-perf` if you touched
   traversal, revoke or gate).
4. Open a focused feature pull request — one concern per PR.
5. Wait for the preview deployment to report ready. A PR without a deployment-ready
   signal is not testable; do not skip this step and call the PR done.
6. Let TestSprite run its configured suite against that preview automatically.
7. Read the actual TestSprite results on the PR. Open the report; do not infer.
8. Fix legitimate failures at the cause, not by relaxing the assertion.
9. Push the fix and confirm the rerun.
10. Keep the passing PR as regression evidence.

Rules that make this honest:

- Unit tests are **not** evidence that TestSprite ran. Only a real TestSprite result on
  the PR is.
- Never fake a green result, weaken an assertion, delete a scenario, or disable a check
  to make a PR pass. A failing test is information; report it.
- Never manufacture a failure for a demo.
- Do not reimplement TestSprite's checks as a substitute GitHub Action. The service's
  own execution and PR comment/check is the signal.
- Once the suite is stable, let it block PRs.

## 6. Product-first priorities

- Fix release-blocking reliability and security defects before optional feature work.
- Take features from the actual roadmap (`docs/PROGRESS.md`, `docs/FEATURES.md`), not
  from whatever is easiest to demonstrate.
- Prefer changes that satisfy several genuine requirements at once.
- Do not build features whose only purpose is a demonstration.
- The product's identity is independent of any third-party service. Automated testing,
  hosting providers and databases are infrastructure; none of them belong in the
  product's name, architecture, feature list or user-facing copy.
- Public-facing text (README, UI, docs, commit subjects, PR titles) describes the
  product. Keep internal coordination notes, account details and submission
  material out of the tracked repository.

## 7. Coordination

- Multiple agents work in this repository, in separate sessions and sometimes in the
  same worktree.
- `docs/DEVELOPMENT_HANDOFF.md` is the shared status board. Claim a work area there
  before starting a substantial change, and update it when a milestone moves.
- Claim **one** work area per agent. Do not start a feature another agent has claimed.
- Publish a reusable, reviewed commit; do not depend on instructions that exist only in
  one worktree or one conversation.
- `docs/consults/NNN-<topic>/` is the record for anything genuinely uncertain —
  question, evidence, decision. One unresolved question becomes a task; it does not
  become a guess.
- When you stop, leave the tree in a state another agent can resume from: say what you
  did, what you verified, and what is still open.