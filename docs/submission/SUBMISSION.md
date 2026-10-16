# SUBMISSION - draft pending final review

Draft factual copy awaiting final statistician and human submission review. Placeholders in
`<angle brackets>` remain for repo visibility, video and live URL. Local verification is scoped
to the tested subsets in `docs/FEATURES.md`; this draft is not publication approval.

## Project name

**Pedigree — git blame and git revert for what an AI agent believes**

## One-liner

Pedigree records observed or reported agent lineage in FalkorDB, so you can revoke a recorded bad
source, inspect its recorded downstream effects, retain supported items, and gate
risky actions with the lineage path as evidence.

## Long description

Coding agents remember things and act on them: prompt files, rule files, MCP tool descriptions,
pages they read, memories they write. When one of those sources turns out to be wrong or
malicious, nobody can answer *what did the agent already believe and do because of it?*

Pedigree records lineage through a Claude Code hook, REST API and MCP. Runtime observations
and agent-reported dependencies remain distinct. The OpenCode adapter is unbuilt; a temporary
observation plugin captured one genuine read-hook shape. The lineage is stored in **FalkorDB** as
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
  (`~ped:<tenant>`) verified against real ACL users on v4.22.1. The service still shares
  administrative DB credentials; tenant-specific credential wiring remains open.

What is honest about it: the algorithm family is known (PACMI, MemoRepair, MAP-Graph, CaMeL/FIDES),
and the implementation combines capture interfaces, independent-support preservation,
structural authority rules, an isolation/concurrency suite and measured results. E1 compares six
repair semantics on `18` generated cells x `30` seeds against an *independent* oracle (Pedigree:
recall `1.0`, over-invalidation `0.0`; full cascade: `0.0493` pooled / `0.2777` in the deepest
cell; flat one-hop: recall `0.1862`). E2 models capture error: `1%` missing edges leak `0.012`,
the conservative read window flags extra items equal to `4.4628`-`5.7193` times the truly
affected item count. Every number comes from committed
scripts (`make eval`) into `docs/NUMBERS.md`, and `make check` fails if the README cites anything
else. Local E1/E2, E3 S1/S6/S8, E4/E4b measurements exist; the repaired F-14 publication
pipeline has scoped statistical signoff (`docs/qa/F-14.md`). E3b/E6 coverage and benign friction are NOT
MEASURED. F-17 what-if and F-18 audit have independent QA/red-team PASS for local subsets;
checkpoint/restore and WCC remain unbuilt, and what-if concurrency admission is process-local.

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
in the UI and the gate can be exercised from the UI form or `curl`. `make eval-quick` runs
a subset and writes isolated quick artifacts; it does not replace published full measurements.

## AI disclosure paragraph (for the form)

AI assistants contributed implementation, tests and review. Decisions and repository evidence
are recorded in `docs/DECISIONS.md`, consults and `docs/qa/`; the numerical pipeline is scripted
and remains subject to final statistician review. This draft does not attest that the human
submitter personally verified every query, algorithm or measurement, or completed a live
walkthrough. The human submitter must review the final disclosure and submission before use.

## What is deliberately NOT claimed

- A shipped OpenCode adapter or full installed-runtime coverage (one genuine read-hook payload
  from a temporary observation plugin is recorded; this does not establish complete capture).
- Per-tenant DB ACL users wired into the service (verified by a real ACL test, wiring tracked).
- E3b/E6 real-session coverage and benign gate friction, the complete planned attack zoo,
  and the hosted deployment (a human step). Local E3 S1/S6/S8, E4/E4b and isolation checks
  are distinct from those unmeasured items.
