# Pedigree

**git blame and git revert for what an AI agent believes.**

Coding agents remember things and act on them: prompt files, rule files, MCP tool
descriptions, web pages they read, memories they write. When one of those sources turns
out to be wrong or malicious, nobody can answer *"what did the agent already believe and do
because of it?"*. Pedigree records, out of band (Claude Code hooks, an OpenCode plugin,
MCP), where every memory, rule and action came from; stores that lineage in **FalkorDB**
(one graph per tenant); and lets you **revoke** a bad source, see everything it
contaminated **down to the commit**, **keep what is independently supported**, and **gate
risky actions** with the lineage path as evidence.

> Status: under active construction for the WeMakeDevs × FalkorDB *Graph Hacks* hackathon
> (Oct 15–18 2026). The README status table is generated from `docs/FEATURES.md` and only
> lists features whose tests and QA evidence exist in this repository.

## Why a graph?

A join can see two things at once. The graph sees the commit six hops away — and can say
*why* it is implicated, along which path, and what still has independent support. All
graph work (revocation cascade, blame, impact, what-if, load-bearing sources) runs as
fixed, parameterised Cypher on FalkorDB; remove FalkorDB and the product stops working.

## Quick start

```bash
git clone <repo-url> && cd pedigree
make setup          # creates .venv and installs the package (Python 3.11+)
make start-db       # FalkorDB v4.22.1 (Docker image, or pinned .so without Docker on Linux)
make test-quick     # runs the fast test suite against the real FalkorDB
make demo           # seeds the demo tenant, prints the UI/MCP URLs
```

Full setup, the graph data model and **every Cypher query and algorithm the product
depends on** are documented below and in `docs/` (see `docs/WALKTHROUGH.md` for a guided,
runnable tour). *(Completed during the build; do not trust this file for a claim that is
not also in `docs/FEATURES.md`.)*

## Tracks entered

- **Track 2 — Agent Memory and Coordination** (primary)
- **Track 1 — Agents That Act on Connected Data** (secondary)

Decision record: `docs/DECISIONS.md` ADR-000.

## Documentation map

| Doc | What it is |
|---|---|
| `docs/01-IDEA.md` | product specification (problem, data model, algorithms) |
| `docs/02-ARCHITECTURE.md` | components, consistency strategy, threat model |
| `docs/03-EVAL-AND-DEMO.md` | evaluation design, baselines, demo script |
| `docs/04-AGENT-OPERATING-SYSTEM.md` | how this repo was built with AI agents |
| `docs/05-PHASES.md` | the time-boxed plan and acceptance tests |
| `docs/DECISIONS.md` | architecture decision records (plain language) |
| `docs/PROGRESS.md` | dated build log with evidence |
| `docs/FEATURES.md` | feature → status → tests → QA report |
| `docs/WALKTHROUGH.md` | every query and decision explained, with runnable commands |
| `docs/NUMBERS.md` | the only allowed source of numbers for README/blog/video |

## License

MIT — see `LICENSE`.
