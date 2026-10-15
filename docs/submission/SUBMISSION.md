# SUBMISSION - ready-to-paste form text

Verified facts only. Placeholders in `<angle brackets>` are the human's to fill (repo visibility,
video URL, live URL). Nothing here claims a feature that is not `done` in `docs/FEATURES.md`.

## Project name

**Pedigree — git blame and git revert for what an AI agent believes**

## One-liner

Pedigree records where every agent belief came from in FalkorDB, so you can revoke a bad source,
see everything it contaminated down to the commit, keep what is independently supported, and gate
risky actions with the lineage path as evidence.

## Long description

Coding agents remember things and act on them: prompt files, rule files, MCP tool descriptions,
pages they read, memories they write. When one of those sources turns out to be wrong or
malicious, nobody can answer *what did the agent already believe and do because of it?*

Pedigree answers that out of band. A Claude Code hook, an OpenCode plugin, the REST API or MCP
capture lineage (nothing the model writes is evidence). The lineage is stored in **FalkorDB** as
one graph per tenant, `ped:<tenant>`, and every product operation is a graph operation on it:

- **Revoke** one source: an atomic barrier marks it revoked, a chunked BFS fixpoint quarantines the
  closure, final statuses are computed in topological order (`preserved` when independent support
  exists, otherwise `tainted`), written back in chunks and verified, crash-safe and resumable.
- **Blame / impact**: `algo.BFS` over mirrored `DERIVED_FROM`/`FEEDS` edges gives ancestors and
  descendants with the reason path; unknown ids answer `not_in_graph` rather than "safe".
- **Gate** a risky action: a deterministic allow/warn/reverify/block decision over the stored
  status labels, with the lineage path as the reason, exposed as `/v1/gate`, MCP
  `check_action` and the Claude Code `PreToolUse` hook (`deny`/`ask`).
- **Isolation**: tenant from the bearer token only, one graph per tenant, per-tenant ACL pattern
  (`~ped:<tenant>`) verified against real ACL users on v4.22.1.

What is honest about it: the algorithm family is known (PACMI, MemoRepair, MAP-Graph, CaMeL/FIDES),
and the contribution here is capture from real runtimes, independent-support preservation,
structural authority rules, an isolation/concurrency suite and measured results. E1 compares six
repair semantics on `18` generated cells x `30` seeds against an *independent* oracle (Pedigree:
recall `1.0`, over-invalidation `0.0`; full cascade: `0.0493` pooled / `0.2777` in the deepest
cell; flat one-hop: recall `0.1862`). E2 models capture error: `1%` missing edges leak `0.012`,
the conservative read window over-flags by `4.4628`-`5.7193`. Every number comes from committed
scripts (`make eval`) into `docs/NUMBERS.md`, and `make check` fails if the README cites anything
else.

## Tracks entered

- **Track 2 — Agent Memory and Coordination** (primary)
- **Track 1 — Agents That Act on Connected Data** (secondary)

Track decision and the ambiguity note: `docs/DECISIONS.md` ADR-000.

## Tech used

Python 3.12, FastAPI, pydantic v2, FalkorDB 4.22.1 (pinned, BFS/PageRank/GRAPH.COPY, one graph per
tenant), MCP (stdio + Streamable HTTP), Claude Code hooks (stdlib-only adapter), a static
TypeScript-free workspace (no build step), pytest + hypothesis against a real FalkorDB, Docker.

## Repo URL

<public-repo-url>

## Demo video URL

<youtube-url>

## Live demo URL

<render-or-other-url, or "local only — see README Deploy">

## Install notes for a judge

```bash
git clone <public-repo-url> && cd pedigree
make setup && make start-db && make test-quick && make demo
.venv/Scripts/python.exe -m pedigree.cli serve     # Windows; .venv/bin/python on Linux
```

The workspace then opens with the seeded synthetic S1/S8 lineage; revoke dry-run → confirm works
in the UI and the gate can be exercised from the UI form or `curl`. `make eval-quick` regenerates
the headline measurement in about four seconds.

## AI disclosure paragraph (for the form)

This project was built with an AI coding assistant (OpenCode with a hosted model) acting as the
implementation and review engine under my direction. Every Cypher query, algorithm and decision
was written or verified by me: decisions are recorded in plain language in `docs/DECISIONS.md`,
each feature has an independent QA report in `docs/qa/`, and every published number is produced by
committed evaluation scripts and enforced by `scripts/check_numbers.py`. I can walk the graph
model, each query, the barrier protocol and the gate rules live.

## What is deliberately NOT claimed

- Installed-runtime capture for OpenCode (free provider quota during the build; artifacts record
  the limitation honestly instead of fabricating traces).
- Per-tenant DB ACL users wired into the service (verified by a real ACL test, wiring tracked).
- E3-E6 evaluations (E1 and E2 are done and reported), the hosted deployment (a human step).
