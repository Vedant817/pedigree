# How to un-poison an agent's memory

*(AI-assisted draft for dev.to / the WeMakeDevs community blog, pending human author review.
First-person passages are proposed copy, not an attestation of personal verification.
Numerical text is awaiting the coherent evaluation rerun and final statistician review;
source-link and snippet checks remain pre-publication tasks.)*

Repo: <repo-url> · Video: <video-url> · Live demo: <deploy-url or "local only, see README">

Consider an agent that reads a web page, summarizes it into a memory file, and later writes
code that follows the summary. If the page is hostile, the question is: **which of the agent's beliefs, files and commits came from that
page?** Not "did it read the page" - that was in the transcript - but *what did it end up
believing and doing because of it*. This class of attack is documented: a poisoned page can
persist through an agent's memory and be invoked much later
([embracethered, 2025](https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/)),
and a rules file is enough to steer a code agent
([Pillar Security, 2025](https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents/)).

I built **Pedigree** for the WeMakeDevs x FalkorDB *Graph Hacks* hackathon: git blame and git
revert for what an AI agent believes. This post is what I learned, including the parts where the
obvious answer was wrong.

## Why the usual tools cannot answer it

Vector memory stores embeddings, not derivations: "delete the poisoned item" matches by
similarity, so it deletes whatever reads like the bad source instead of what *descends* from it.
Graphiti-style `remove_episode` removes items whose *first* provenance is the episode
([graphiti_core/graphiti.py](https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py)),
which keeps shared/derived beliefs that were also seeded by the poisoned episode. Time-travel
rewinds everything created after a point - recall by construction, with no idea what was
unrelated.

All three are *lineage* questions, and lineage is a graph problem: which nodes are downstream of
this one, along which path, and which of them had independent support.

## What Pedigree does

- **Record lineage** through the Claude Code hook, REST API and MCP. Runtime observations and
  agent-reported dependencies are distinct evidence. The OpenCode adapter is unbuilt; a
  temporary observation plugin captured one genuine read-hook shape.
- **Revoke**: mark one source bad and the engine finds everything downstream, down to the commit,
  with a reason path for each.
- **Preserve**: a belief that also has an independent, human-attested supporting source survives
  instead of being caught in the cascade.
- **Gate**: before a risky action, return allow / warn / reverify / block with the lineage path as
  the reason, and *not in the graph* for ids we never captured.
- **Isolate**: one FalkorDB graph per tenant, auth from the token only.

I want to credit the prior art properly, because the *algorithm* here is not new: PACMI
([arXiv](https://arxiv.org/html/2610.05732v1)) for cascading invalidation over a typed
dependency graph, MemoRepair ([arXiv](https://arxiv.org/abs/2605.07242)) for the
missing-edges analysis, MAP-Graph ([arXiv](https://arxiv.org/abs/2608.10509)) for an
action gate with Allow/Block/Reverify, and CaMeL/FIDES ([arXiv](https://arxiv.org/abs/2505.23643))
for the declassification discipline. The implementation combines capture interfaces,
preservation, joint integrity/confidentiality labels, an isolation suite, and local measurements.
Installed-runtime coverage remains unmeasured.

## The graph model

One graph per tenant, `ped:<tenant>`. Every node is `:Node` plus a type: `Source`, `Memory`,
`Action`, `Session`, `Agent`, `Revocation`. Lineage is `(child)-[:DERIVED_FROM]->(parent)`, and I
mirror it with `(parent)-[:FEEDS]->(child)`.

The mirror is not decoration: FalkorDB's `algo.BFS` follows exactly **one** outgoing relationship
type, so a cascade that must walk *down* and a blame path that must walk *up* each get their own
edge type, instead of a var-length `DERIVED_FROM*1..12` that the profiler expands per row. Status
(`ok | quarantined | tainted | preserved | revoked`), `taint_parent`, `low_integrity` and `conf_eff`
are stored, so the gate is one read and the UI is honest about *why*.

## The queries that matter

```cypher
// impact: everything downstream of a source, bounded depth, over the mirrored FEEDS edges
MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes
UNWIND nodes AS n RETURN n.id, n.status
```

```cypher
// ingest with parents: create the node, attach parents, mirror the edges, inherit labels and
// born-quarantined status, all in ONE query
CREATE (c:Node:Memory) SET c = $props, c.created_at = $now
WITH c UNWIND $parents AS pid MATCH (p:Node {id:pid})
MERGE (c)-[d:DERIVED_FROM]->(p) SET d.rel = $rel, d.via = $via
MERGE (p)-[:FEEDS]->(c)
WITH c, collect(p) AS ps
SET c.status = CASE WHEN any(p IN ps WHERE p.status IN ['revoked','tainted','quarantined'])
                    THEN 'quarantined' ELSE 'ok' END
```

```cypher
// source identity: the artifact names the node, so re-reading a file cannot fork the lineage
MERGE (n:Node:Source {tenant:$tenant, uri:$uri, content_hash:$hash})
ON CREATE SET n = $props, n.created_at = $now
RETURN n.id, n.status, n.low_integrity, n.conf_eff
```

`docs/WALKTHROUGH.md` explains each of these with the product question it answers and a runnable
command against a seeded tenant.

## The part that surprised me

Two things went wrong before they went right.

**Races.** If a revoke runs while the agent is still writing memories, a memory can be created
*after* the cascade read its parents and *before* the status write. I closed it with a barrier:
the revoke marks the root and a `:Revocation {state:'running'}` in one atomic query, then a
fixpoint sets the closure to `quarantined` in chunks, then the final statuses are computed in
topological order and written back. Anything written during the cascade is *born quarantined*,
because its parent was quarantined when it was created. Scoped race tests exercise this
behavior; they do not prove every concurrent execution is safe.

**Don't throw the baby out.** A full cascade also deletes beliefs that had independent support.
So the fixpoint keeps a node `preserved` when a healthy corroborating source exists, and a node
whose only bad parent became `preserved` is simply `ok`. That is the difference I could measure:
with `18` generated cells x `30` seeds, the full-cascade baseline over-invalidates `0.0493` of
unrelated items pooled - and `0.2777` in the deepest cell - while Pedigree over-invalidates `0.0`
and assigns the expected explicit preservation statuses in this synthetic model
(`evals/REPORT.md`). That column measures status sensitivity, not retention precision;
baseline zero scores do not mean all supported items were discarded. A flat one-hop
invalidation detects `0.1862` of the true contamination pooled.

## Capture is the hard part

MemoRepair's finding that a small fraction of missing lineage edges can leak a lot of
contamination ([arXiv](https://arxiv.org/pdf/2605.07242v1/__stdout.txt)) is the part I
could reproduce in a model: dropping `1%` of lineage edges leaves `0.012` of the contamination
undetected, `2%` leaves `0.0434`, `5%` leaves `0.1414`, `10%` leaves `0.2412`
(`evals/run_e2.py`). The conservative read-window capture - "this session read these K things" -
never misses, but flags extra items equal to `4.4628`-`5.7193` times the truly-affected item
count and extra actions equal to roughly `3.3` times the truly-affected action count.
These ratios exclude correctly flagged items/actions from their numerator. That is the
trade of a window: extra flags in exchange for not
being blind in this synthetic model. These are modeled over-flagging ratios, not measured
benign-session gate friction; E3b/E6 are NOT MEASURED.

## The demo, in prose

The current local demo seeds synthetic S1/S8 lineage. Click the poisoned source, run the
dry-run revoke, drag the depth slider from one to six and watch the contamination wave reach the
commit, then submit a synthetic `git push` proposal to the gate form and inspect its evidence. Ask
`impact` about an id we never captured and it says *not in the graph* instead of guessing.

## Honest limitations

Pedigree **contains, explains and reverts**; it does not detect a bad source and does not prevent
prompt injection. My E1 numbers quantify baseline *semantics* against built-in ground truth, not
lineage discovery; E2 is a *model* of capture error, not a measurement of a real runtime; the
window over-approximates on purpose. `preserved` is only as good as the corroboration signal, and
trusted human/scanner attestation over REST requires the operator credential under the
source-identity/trust ADR-008. MCP agents can assert only agent-level corroboration and cannot
upgrade it to trusted support by naming a human or scanner. Hooks see only
what the runtime exposes, bash risk classification is a documented regex heuristic, and external
effects (pushes already pulled) are listed, not undone.

## How to run it

```bash
git clone <repo-url> && cd pedigree
make setup && make start-db && make test-quick && make demo
.venv/Scripts/python.exe -m pedigree.cli serve     # or docker compose up --build
```

MCP config and the Claude Code hook are in the README. A bounded free OpenCode session
captured genuine before/after payloads for one read. Full adapter coverage, real-session
coverage and benign gate friction remain unmeasured. The Claude hook has contract and localhost
HTTP evidence, not installed-Claude-runtime proof. F-17 what-if and F-18 audit have independent
QA PASS for their local subsets; checkpoint/restore and WCC remain unbuilt, and what-if admission
is process-local. ACL mechanism checks pass separately; the service still shares administrative
DB credentials. Local E1/E2, E3 S1/S6/S8, E4/E4b measurements have scoped F-14 statistician signoff.

## What I learned

Repository tests and consults record several FalkorDB details: `MATCH` after
`UNWIND` silently drops missing parents, so an ingest that expects three parents and finds two
must fail loudly rather than write a half-linked node; `MULTI/EXEC` is not the atomic unit
the original design assumed; index builds are asynchronous, so a unique constraint created before its supporting
index is a different bug than a duplicate row; and the ACL key pattern `~ped:abc` cannot match
tenant `abcd` precisely because tenant ids are min-length-bounded. Each of those is now a test.

The bigger lesson: the interesting part of agent memory is not retrieval, it is *accountability*.
If you cannot answer "what did the agent believe because of this, and what did it do about it",
you do not have memory - you have a cache.

## One more honest measurement

I picked FalkorDB because a graph felt like the right shape, so I tested that assumption rather
than asserting it (`evals/run_e4b_sqlite.py`): the same descendant closure and ancestor queries in
stdlib `sqlite3` with a recursive CTE versus FalkorDB's `algo.BFS`, on the same generated DAG,
with descendant and ancestor ID sets asserted equal. **The recorded local traversal comparison favored the CTE** - the graph query
pays a round-trip. This implementation uses one graph per tenant, `GRAPH.COPY` for an
isolated what-if, and the per-graph ACL mechanism. SQLite can also implement logical isolation;
this benchmark does not compare isolation architectures or the whole revoke pipeline. If your problem is only "find the descendants of a node", a recursive
CTE in your existing database is the honest answer - and I would rather say that in a hackathon
for a graph database than pretend the graph made the loop faster.

*AI disclosure draft, pending human review: AI assistants contributed implementation, tests
and review. Repository evidence and decisions are recorded in `docs/qa/`, consults and
`docs/DECISIONS.md`. No claim is made here that the human author has personally verified every
query, decision or measurement. Final author attribution and disclosure require human approval;
see `AI_DISCLOSURE.md`.*

---

## Quality checklist (before publishing)

- [ ] Every number in `docs/NUMBERS.md` - `scripts/check_numbers.py` PASS.
- [ ] Every link opens; the papers and posts are the ones actually cited in the repo docs.
- [ ] Every snippet copy-pasted from the repo at the tagged commit.
- [ ] Screenshots at mobile width, no tokens visible in any screenshot.
- [ ] First three lines work as a standalone summary.
- [ ] One call to action (try the repo / watch the video).
