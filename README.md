# Pedigree

**git blame and git revert for what an AI agent believes.**

Coding agents remember things and act on them: prompt files, rule files, MCP tool
descriptions, web pages they read, memories they write. When one of those sources turns out to be
wrong or malicious, nobody can answer *"what did the agent already believe and do because of it?"*

Pedigree answers that out-of-band:

- it **captures** where every belief came from (a Claude Code hook, the OpenCode plugin, the REST
  API or MCP - never the model's own word),
- stores the lineage in **FalkorDB**, one graph per tenant, as fixed parameterised Cypher,
- **revokes** a bad source and shows what it contaminated down to the commit,
- **keeps what is independently supported** instead of cascading blindly,
- **gates** risky actions with the lineage path as evidence, and says
  *not in the graph* rather than "safe" about unknown ids.

> Built for the WeMakeDevs × FalkorDB **Graph Hacks: Context for AI Agents** hackathon
> (Oct 15-18 2026). The status table below is kept in sync with `docs/FEATURES.md`: a feature
> counts as done only when its tests and its QA evidence exist in this repository.

## Why a graph (and why FalkorDB is not decoration)

Every question Pedigree answers is a graph question:

| Question | What it needs |
|---|---|
| What did this belief come from? | multi-hop ancestor traversal (`algo.BFS` over `DERIVED_FROM`) |
| What depends on this source? | descendants over the mirrored `FEEDS` edges, chunked |
| Is this action safe to run? | the status labels the revoke fixpoint already computed, plus one `taint_parent` hop chain as the reason path |
| Which sources carry the most weight? | `algo.pageRank` over `Node`/`DERIVED_FROM` |
| What would revoking this do? | `GRAPH.COPY` of the tenant graph, the real revoke on the copy, diff, delete |

If you remove FalkorDB, none of those stay: the product stops working. There is no
database-agnostic fallback, and the isolation story (one graph per tenant) *is* the multi-graph
story. A recursive SQL CTE can compute a closure - we measured that comparison honestly
(`evals/run_e4b_sqlite.py` is the remaining item) - but the per-tenant graph namespace, the copy
for what-if and the ACL pattern are the parts a relational store does not give us.

## Quick start (local, mandatory path)

```bash
git clone <repo-url> && cd pedigree
make setup          # .venv + the package (Python 3.11+)
make start-db       # FalkorDB v4.22.1 - Docker image, or the pinned .so without Docker on Linux
make db-status      # reachable + module version check
make test-quick     # the fast test suite against a REAL FalkorDB (no mocks of graph logic)
make demo           # seeds synthetic scenarios S1+S8 into tenant `demo`; writes a private
                    #   credential to an ignored path and prints it
.venv/Scripts/python.exe -m pedigree.cli serve     # Windows
.venv/bin/python -m pedigree.cli serve             # Linux/macOS
```

Then open the printed local URL, paste the token `make demo` printed, and the workspace loads
the seeded lineage. Previewing a revocation changes nothing until you confirm it.

Docs: [full setup](#setup) · [data model](#graph-data-model) ·
[Cypher inventory](#the-cypher-the-product-depends-on) ·
[security model](#security-model) · [evaluation](#evaluation) ·
[limitations](#honest-limitations) · [deploy](#deploy) ·
[guided tour](docs/WALKTHROUGH.md) · [decisions](docs/DECISIONS.md) ·
[build log](docs/PROGRESS.md) · [features](docs/FEATURES.md) · [numbers](docs/NUMBERS.md)

## Architecture

```
 Claude Code hook   OpenCode plugin   REST client   MCP client
      |                   |               |             |
      v                   v               v             v
  POST /v1/events ---- POST /v1/* ---- MCP (stdio / streamable HTTP at /mcp)
      |                   |               |             |
      +-------------------+---------------+-------------+
                          v
              service layer (engine/*.py)   <- deterministic, no LLM
      ingest -> revoke/blame/impact -> gate -> invariants
                          v
        static parameterised Cypher (db/queries.py)
                          v
   FalkorDB 4.22.1   ped:<tenant> per tenant  +  ped:registry (tokens)
```

Capture is the choke point: runtimes send evidence of what happened, `src/pedigree/adapters.py`
translates the fields we understand into engine operations, and everything else is ignored rather
than guessed. Nothing the model writes becomes lineage; only hooks/API calls do.

## Graph data model

One graph per tenant, `ped:<tenant>` (ids are `^[a-z0-9]{3,24}$`, so the ACL pattern
`~ped:abc` can never match tenant `abcd`). The registry graph `ped:registry` holds
`Tenant{id, status, node_cap, created_at, token_sha256}` - only a sha256, never the token.

Nodes (`all :Node` + a type label): `Source` (a prompt, a file, a web page, a tool output, an MCP
tool description), `Memory` (a belief), `Action` (a tool call with `effect`/`risk`/`artifacts`),
`Session`, `Agent`, `Revocation` (whose lifecycle property is `state`, ADR-006).

Edges: `(child)-[:DERIVED_FROM {rel, via}]->(parent)` mirrored by `(parent)-[:FEEDS]->(child)`
(the mirror is what `algo.BFS` follows - it only traverses one relationship type), and
`(Memory)-[:CORROBORATED_BY {by}]->(Source)` for independent support.

Properties that carry the semantics:

| Property | Meaning |
|---|---|
| `status` | `ok \| quarantined \| tainted \| preserved \| revoked` - the materialised containment decision |
| `taint_parent` | for a `tainted` node, the parent that explains it (the path you show the user) |
| `low_integrity` | OR over parents at write time; the gate's "untrusted influence" input |
| `conf` / `conf_eff` | confidentiality tags, unioned over parents at write time, immutable afterwards |
| `artifact_key` | `path@sha256` for a write - how a later session links to what an earlier one wrote |
| `integrity`, `content_hash`, `uri` | Source identity: `(uri, content_hash)` names one node (ADR-008) |

**Born-quarantined:** a child of a `revoked|tainted|quarantined` parent is created `quarantined`.
**Preservation:** after a revoke, a dependent with a healthy independent corroborating source is
`preserved`, and a node whose only bad parent became `preserved` is `ok` - which is why the status
must be computed in topological order (`src/pedigree/engine/compute.py`, cross-checked against an
independent oracle on generated DAGs).

## The Cypher the product depends on

All of it lives in `src/pedigree/db/queries.py` as constants with parameters only; a lint test
(`tests/unit/test_queries_static.py`) fails the build on any interpolated value.

| Purpose | Shape (abridged) |
|---|---|
| Descendants (impact) | `MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes UNWIND nodes AS n RETURN n.id, n.status` |
| Ancestors (blame) | same over `'DERIVED_FROM'` |
| Reason path | `MATCH (n:Node {id:$id}) RETURN n.taint_parent` walked hop by hop, bounded |
| Revoke barrier | `MERGE` the `:Revocation` root, then chunked `SET n.status='quarantined'` over the discovered closure |
| Final statuses | read `Q_PARENTS_OF` + `Q_SUPPORT_OF`, compute in topological order in Python, chunked `UNWIND $b ... SET n.status = b[1][0], n.taint_parent = b[1][1]` |
| One atomic ingest with parents | `CREATE (c:Node:{label}) ... WITH c UNWIND $parents AS pid MATCH (p:Node {id:pid}) MERGE (c)-[:DERIVED_FROM]->(p) ... DERIVED_FROM/FEEDS mirror + label inheritance in one query` |
| Source identity | `MERGE (n:Node:Source {tenant:$tenant, uri:$uri, content_hash:$hash}) ON CREATE SET ...` under a composite unique constraint `Source(uri, content_hash)` |
| Corroboration (write-once-then-upgrade) | `MERGE (m)-[r:CORROBORATED_BY]->(s) SET r.by = CASE WHEN r.by IS NULL THEN $by WHEN $by IN ['human','scanner'] THEN $by ELSE r.by END` |
| Read window | `MATCH (se:Session {id:$sess})-[r:READ]->(n:Node) WITH n, max(r.at) AS at ORDER BY at DESC LIMIT $k` |
| Gate input | one chunked read of the anchor ids returning `status`, `low_integrity`, `conf_eff`, `taint_parent` |
| Load-bearing sources | `CALL algo.pageRank('Node','DERIVED_FROM') YIELD node, score WHERE 'Source' IN labels(node)` + exact descendant counts by BFS |
| What-if | `g.copy('ped:<tenant>:wi:<hex>')`, the real revoke on the copy, diff, `delete()` |
| Invariants | a family of `count(*)` probes (missing status, bad taint parent, `ok` node under a bad parent, missing mirror, foreign tenant, ...) |

`docs/WALKTHROUGH.md` explains each of these with the product question it answers and a runnable
command against a seeded tenant.

## Interfaces

### REST (`/v1/*`, bearer token per tenant)

`POST /v1/events` (capture adapters) · `/v1/sources` · `/v1/memories` · `/v1/actions` ·
`/v1/corroborate` · `/v1/sessions` · `/v1/sessions/read` · `/v1/revoke` (dry-run first) ·
`/v1/reinstate` · `GET /v1/blame/{id}` · `/v1/impact/{id}` · `/v1/gate` · `/v1/graph` ·
`/v1/stats` · `/v1/artifacts/lookup` · `/v1/invariants` · `/` (static workspace) ·
`/healthz` `/readyz` `/metrics` `/docs` · `POST /admin/tenants` (operator token).

Errors are typed and never leak a stack trace; every response carries a correlation id. The
mapping (also in `docs/01-IDEA.md`, the interface section):

```
invalid_argument 422 | unauthorized 401 | forbidden 403 | not_in_graph 404 | conflict 409
too_large 413 | rate_limited 429 (+ Retry-After) | quota_exceeded 429 | timeout 504 | internal 500
```

### MCP (server name `pedigree`)

Streamable HTTP at `/mcp` and stdio. Tools: `pedigree_health`, `pedigree_record_source`,
`pedigree_remember`, `pedigree_record_action`, `pedigree_corroborate` (agent-asserted support
only), `pedigree_revoke`, `pedigree_reinstate`, `pedigree_blame`, `pedigree_impact`,
`pedigree_check_action`, `pedigree_report`. The tenant comes from the token, never from a tool
argument, and the LLM never writes Cypher.

```json
// .opencode/opencode.json or Claude Code MCP config
{ "mcpServers": { "pedigree": { "type": "http",
    "url": "http://127.0.0.1:8000/mcp",
    "headers": { "Authorization": "Bearer <tenant-token>" } } } }
```

### Claude Code hook

`adapters/claude/` ships a stdlib-only hook (`pedigree_hook.py`) driven by
`settings.example.json`: `UserPromptSubmit`, `PreToolUse` (matcher `Bash|Write|Edit|MultiEdit|
mcp__.*`) and `PostToolUse` (`*`). On `PreToolUse` it asks `/v1/gate` and prints the
`permissionDecision` JSON (`deny` for a block, `ask` for a reverify). Hook failures fail **open**
documented (a stalled hook must not block the tool unless the matcher sets
`"onFailure":"block"`).

### OpenCode plugin

`.opencode/plugins/pedigree.ts` posts the same `/v1/events`. The plugin starts and is captured by
tests, but a free provider quota blocked end-to-end session capture during the build - the honest
state is in `docs/KNOWN_ISSUES.md`; nothing was fabricated to fill the gap.

## Security model

- **Identity:** a tenant token (`ped_<tenant>_<32 urlsafe>`) resolves to exactly one graph; the
  tenant never comes from a body field, a query parameter or a tool argument.
- **Isolation:** one graph per tenant; every query is scoped to `graph_name(tenant)`. Cross-tenant
  ids return `not_in_graph` (or `reverify` from the gate - unknown lineage is never "safe").
  Per-tenant DB ACL users are **verified** (a test provisions real ACL users scoped to
  `~ped:<tenant>` and proves cross-namespace denial on v4.22.1) but the shipped service still
  connects with the shared credentials - documented as an open item, not claimed.
- **Authority:** the agent channel can only *downgrade*. Sources captured over HTTP are always
  untrusted whatever the payload claims, trusted-by-default kinds need the operator credential,
  and `CORROBORATED_BY` never lets an agent overwrite a human/scanner attestation (ADR-008). The
  gate's "independent support" trust therefore rests on a human or scanner signal, not on anything
  the agent can write.
- **Input surface:** static parameterised Cypher with a lint gate, id/URI/artifact validation,
  body-size and array caps, per-tenant rate limits and node quotas, bounded query timeouts, and
  the registry tenant id reserved.
- **No secrets in the repo:** `.env` is ignored, `.env.example` is committed, a secret scan runs
  over the working tree *and* the git history in `make check`.

## Evaluation

Real numbers only, produced by committed scripts (`make eval`) and regenerated into
`docs/NUMBERS.md`; `make check` fails if a number in this file is not there.

**E1 - contamination semantics** (`evals/run_e1.py`; generated lineage DAGs, one revoked source,
ground truth from an *independent* oracle; Pedigree's column is the engine's real `compute_final`,
cross-checked against a real FalkorDB revoke; baselines are documented emulations of the
semantics in the literature, not the vendors' products):

| system | recall | over-invalidation | preserved correct |
|---|---|---|---|
| Pedigree | 1.0 | 0.0 | 1.0 |
| B4 full cascade (no support check) | 1.0 | 0.0493 pooled, **0.2777** in the deepest cell | 0.0 |
| B2 flat 1-hop | 0.1862 | 0.0036 | 0.0 |
| B1 first-provenance | 0.3546 | 0.0181 | 0.0 |
| B0 TF-IDF similarity (theta 0.475, calibrated on disjoint seeds) | 0.4714 | 0.0334 | 0.0 |
| B5 time-travel rewind | 1.0 | 0.9557 | 0.0 |

Every value carries a confidence interval in `evals/REPORT.md`; the deep-cell B4 number is the
cost of a cascade that does not check support, and the B2 number is the cost of only looking one
hop.

**E2 - capture fidelity** (`evals/run_e2.py`; a model of capture error, not a measurement of a
real runtime): dropping `1%` of lineage edges leaves `0.012` of contamination undetected, `2%`
leaves `0.0434`, `5%` leaves `0.1414`, `10%` leaves `0.2412`; the conservative read window never
misses but flags `4.4628`-`5.7193` times the truly-affected items and about `3.3` times the
truly-affected actions. That is the trade the window buys, stated as measured.

**Isolation / concurrency** (`tests/integration/test_isolation_concurrency.py`): an isolation
matrix plus `20` tenants x `8` writer threads, after which every graph passes the invariant
checker, holds exactly what its own writers wrote, and contains zero foreign-tenant nodes; a
revoke racing two ingest writers leaves a consistent graph.

**E4 - latency** (`evals/run_e4.py`; real engine calls, one throwaway graph per size, median over
five rounds, the real revoke measured on a different root per round because a repeat revoke is
idempotent by design):

| nodes | revoke p50 | revoke p95 | blame p50 | impact p50 | gate p50 |
|---|---|---|---|---|---|
| 820 | 119.12 ms | 160.44 ms | 5.37 ms | 13.7 ms | 2.07 ms |
| 2460 | 323.05 ms | 536.73 ms | 5.54 ms | 16.31 ms | 2.29 ms |
| 8200 | 1039.29 ms | 1798.94 ms | 6.34 ms | 17.72 ms | 3.0 ms |

The revoke cost grows with the closure it touches (every descendant is read and written, in
chunks); the gate is a single bounded read, which is the point of materialising status at revoke
time. `build_ms` in the CSV is the per-node write path through the engine, not a bulk loader.

Reproduce: `make eval` (full grid) or `make eval-quick` (one cell).

## Honest limitations

Copied from `docs/03-EVAL-AND-DEMO.md` section 7, which is the source of truth:

- Pedigree **contains, explains and reverts**; it does not detect bad sources and does not prevent
  prompt injection.
- E1 has built-in ground truth: it quantifies baseline *semantics*, not lineage discovery. E2 is
  a *model* of capture error. E3 replays published attack *patterns*, not the papers' experiments.
- Session read-window capture over-approximates influence on purpose (the ratio is measured in E2).
- `preserved` is only as good as the corroboration signal, and after ADR-008 only a human or
  scanner can produce the trusted kind of that signal.
- Hooks see only what the runtime exposes; paraphrase through an unhooked channel is invisible.
- Bash risk classification is a documented regex heuristic, not a sandbox. External effects
  (pushes already pulled, emails sent) are listed, not undone.
- The OpenCode plugin could not be captured end-to-end during the build (free provider quota);
  Claude hook capture is verified against the real HTTP API, not against an installed runtime.
- Per-tenant ACL users are verified but not wired into the service; a single-host deployment where
  the operator token is pasted into an agent's environment still has one principal.
- Cloud Free has no TLS and no persistence; any hosted demo holds synthetic data only.

`docs/KNOWN_ISSUES.md` is the live list, with severities and owners.

## Deploy

Local single container (verified: builds, boots FalkorDB v4.22.1 with the pinned module, seeds the
demo tenant, serves `/healthz`, `/readyz`, the workspace and the gate):

```bash
PEDIGREE_ADMIN_TOKEN=choose-a-token docker compose up --build
# or: docker build -t pedigree . && docker run --rm -p 8000:8000 \
#      -e PEDIGREE_SEED_DEMO=1 -e PEDIGREE_ADMIN_TOKEN=choose-a-token pedigree
curl -s localhost:8000/readyz
```

Render (single web service, same image): create the service from this repository, set
`PEDIGREE_ADMIN_TOKEN` and `PEDIGREE_SEED_DEMO=1`, keep the default port. The Render account
itself is a human step and has not been created yet, so the hosted URL is not claimed here - the
local path above is the tested one.

## Tracks entered

- **Track 2 - Agent Memory and Coordination** (primary)
- **Track 1 - Agents That Act on Connected Data** (secondary)

Rationale and the track-count ambiguity: `docs/DECISIONS.md` ADR-000.

## Status

| ID | Feature | Status | Tests | QA |
|---|---|---|---|---|
| F-01 | skeleton, config, FalkorDB pin, schema, secret scan | done | `tests/unit/test_config.py`, `tests/integration/test_schema.py`, ... | `docs/qa/F-01.md` PASS (round 2) |
| F-02 | ingest engine (record_source/remember/record_action/corroborate) | done | `tests/integration/test_core_scenario.py` | `docs/qa/F-02.md` PASS |
| F-03 | revoke engine (barrier -> fixpoint -> compute -> write -> verify, dry-run, reinstate, resume) | done | `tests/unit/test_compute.py`, ... | `docs/qa/F-03.md` PASS |
| F-04 | blame + impact | done | `tests/unit/test_blame.py`, `tests/integration/test_blame_impact.py` | `docs/qa/F-04.md` PASS |
| F-05 | REST API + registry + auth + limits | done | `tests/integration/test_api.py`, `tests/security/test_security_F05.py` | `docs/qa/F-05.md` PASS |
| F-06 | MCP server (stdio + streamable HTTP) | done | `tests/integration/test_mcp.py` | `docs/qa/F-06.md` PASS |
| F-07 | `/v1/events` capture mapping + artifact links | done | `tests/integration/test_events.py` | `docs/qa/F-07.md` PASS |
| F-08 | OpenCode plugin | blocked | - | free provider quota; `docs/consults/opencode-spike.md` |
| F-09 | lineage workspace (graph view, revoke preview/confirm, gate form) | done | `tests/integration/test_ui_api.py`, `tests/security/test_ui_boundary.py` | `docs/qa/F-09.md` PASS |
| F-10 | scenario JSON + `make demo` | done | `tests/integration/test_demo_seed.py`, `test_demo_qa.py` | `docs/qa/F-10.md` PASS |
| F-11 | gate (`check_action`, `/v1/gate`, hook deny/ask, policy.yaml) | done | `tests/unit/test_gate.py`, `tests/integration/test_gate_*.py` | `docs/qa/F-11.md` PASS |
| F-12 | confidentiality labels + scenario S6 | todo | - | gate rule 2 shipped; scenario pending |
| F-13 | isolation hardening | implementing | `tests/security/test_capture_trust.py`, `test_acl_mechanism.py` | capture trust closed (ADR-008); ACL wiring open |
| F-14 | evaluation harness + NUMBERS pipeline | implementing | `tests/evals/*` | E1 + E2 done (`evals/REPORT.md`); E3-E6 pending |
| F-15 | isolation/concurrency suite | implementing | `tests/integration/test_isolation_concurrency.py` | stress + ACL mechanism green; ACL wiring open |
| F-16 | deployment | done (local) | `Dockerfile`, `scripts/entrypoint.sh`, `docker-compose.yml` | container verified end-to-end; Render is a human step |
| F-17 | what-if (`GRAPH.COPY`) | todo | - | - |
| F-18 | `audit_sources` (PageRank + exact descendant counts) | todo | - | - |
| F-19 | `supersede` (decision rot) | todo | - | - |
| F-20 | evals E3/E3b/E4/E4b/E6 + REPORT | todo | - | - |
| F-21 | workspace polish | todo | - | - |
| F-22 | hook spool/replay when the server is down | todo | - | - |
| F-23 | README/blog/video/submission pack | in progress | - | this pass |

## License

MIT - see `LICENSE`. AI assistance is disclosed in `AI_DISCLOSURE.md`.
