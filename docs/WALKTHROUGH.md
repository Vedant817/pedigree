# WALKTHROUGH - every query and decision, explained simply, with runnable commands

Written so the author can defend the implementation live. Every command below works against a
freshly seeded demo tenant. Start one in two terminals:

```bash
# terminal 1
make start-db && make demo                      # seeds tenant `demo`, prints private credential-file path
.venv/Scripts/python.exe -m pedigree.cli serve  # Windows; .venv/bin/python on Linux
```

```bash
# terminal 2 - operator actions use the private operator credential (never commit it)
TOKEN=$(python -c "import json;print(json.load(open('scratch/demo-demo.json'))['operator_token'])")
H="Authorization: Bearer $TOKEN"
BASE=http://127.0.0.1:8000
curl -s "$BASE/v1/graph" -H "$H"      # what the graph holds right now
matcher() { curl -s "$BASE/v1/graph" -H "$H" | python -c "import json,sys;print(json.load(sys.stdin)['by_status'])"; }
```

The whole tour below is derived from the shipped code (`src/pedigree/db/queries.py`,
`src/pedigree/engine/*.py`) - nothing here is aspirational.

## 1. The data model in one paragraph

A tenant is one FalkorDB graph named `ped:<tenant>`. Inside it, every node is `:Node` plus a type
label: `Source` (something an agent read or was told), `Memory` (a belief it formed), `Action`
(something it did), `Session`, `Agent`, `Revocation`. Lineage is `(child)-[:DERIVED_FROM]->(parent)`
with a mirrored `(parent)-[:FEEDS]->(child)`. Independent support is
`(Memory)-[:CORROBORATED_BY {by}]->(Source)`. Each node carries a `status` (`ok`, `quarantined`,
`tainted`, `preserved`, `revoked`) plus `taint_parent`, `low_integrity` and `conf_eff`.

**Why the mirror?** FalkorDB's `algo.BFS` follows exactly one outgoing relationship type. The
revoke cascade must walk *down* (parents to children), the blame path must walk *up* (child to
parents). Keeping both directions as separate relationship types is cheaper than a var-length
`DERIVED_FROM*1..12` path, which the profiler shows expanding per row.

**Why a status at all?** Because the answer to "is this belief contaminated?" is a graph
computation, and the gate, the UI and the API all need the same answer. Computing it once, in
topological order, and storing it, is what makes the gate one read instead of a traversal.

## 2. Ingest: one query per mutation unit

Recording a belief with its parents is a single query: create the node, attach the parents, mirror
the edges, inherit the labels and the born-quarantined status - atomically (`Q_*CREATE_WITH_PARENTS`
in `db/queries.py`). Read it in the file; the important property is that an ingest can never leave
a half-linked node behind.

```bash
curl -s -X POST "$BASE/v1/sources" -H "$H" -H 'Content-Type: application/json' \
     -d '{"kind":"web","uri":"http://example.test/readme","title":"example"}'
curl -s -X POST "$BASE/v1/memories" -H "$H" -H 'Content-Type: application/json' \
     -d '{"text":"the example page says X","derived_from":["<source-id>"]}'
```

**Decision (ADR-008):** a Source's identity is the artifact, not the caller's id. The query is
`MERGE (n:Node:Source {tenant:$tenant, uri:$uri, content_hash:$hash}) ON CREATE SET n = $props`
under a composite unique constraint `Source(uri, content_hash)`, so reading the same file twice
makes one node (and the same uri with new content is a new, independently revocable version). A
hash-less capture derives a stable id from `sha256(tenant|uri)` instead, because a MERGE keyed on a
NULL `content_hash` is *not* protected by the pair constraint - measured with ten concurrent
writers.

`GET /v1/artifacts/lookup` searches a Memory or Action `artifact_key`. A Source does not
receive that key. Its identity is `(uri, content_hash)`, and the events response returns
the node id. The same file posted three times returns the same id three times.

```bash
# capture the same artifact three times through the hook channel: still one node
HASH=$(python -c "print('a'*64)")
for i in 1 2 3; do curl -s -X POST "$BASE/v1/events" -H "$H" -H 'Content-Type: application/json' \
  -d '{"runtime":"claude-code","events":[{"type":"source","source_kind":"file","uri":"AGENTS.md","content_hash":"'"$HASH"'"}]}'; echo; done
```

## 3. Revoke: barrier, fixpoint, then a write that matches the plan

The revoke is the heart of the product. It runs in four steps and the whole thing survives a crash
(`engine/revoke.py`):

1. **Barrier / CAS.** One atomic query marks the root `revoked` and writes a `:Revocation {state:
   'running'}`. A second revoke of the same root returns `idempotent` instead of a second cascade.
2. **Quarantine fixpoint.** A BFS (`Q_DESCENDANTS`, `algo.BFS` over the mirrored `FEEDS` edges)
   discovers the closure, which is then set to `quarantined` in chunks of 2000 ids. Anything
   written during the cascade is *born quarantined* because its parent was quarantined - that is
   the race the barrier closes.
3. **Compute.** Read the parents (`Q_PARENTS_OF`) and the corroborating sources (`Q_SUPPORT_OF`),
   then compute final statuses in topological order in Python (`engine/compute.py`). A parent is
   bad when it is revoked, tainted, or still quarantined. No bad parent becomes `ok`. A remaining
   bad parent with a corroborating source whose status is `ok` becomes `preserved`; otherwise it
   is `tainted`. A parent that itself became `preserved` is not bad.
4. **Write + verify.** Chunked `UNWIND` write of the final statuses and `taint_parent`, then the
   invariant checker, then `Revocation.state='done'`. If the process dies between 2 and 4 the graph
   stays `quarantined` and `resume_incomplete()` finishes the job.

```bash
# dry run first: what would this revoke touch?
curl -s -X POST "$BASE/v1/revoke" -H "$H" -H 'Content-Type: application/json' \
     -d '{"root_id":"demo_s1_web","reason":"poisoned page","dry_run":true}'
# then the real one
curl -s -X POST "$BASE/v1/revoke" -H "$H" -H 'Content-Type: application/json' \
     -d '{"root_id":"demo_s1_web","reason":"poisoned page"}'
```

### Worked example: six nodes

`demo/scenarios/S1.json` is the six-node chain. It is synthetic. Nothing in it has an
independent corroborating source, so preservation does not appear here. After a revoke of
`demo_s1_web`, the fixture's expected statuses are:

| id | kind | after revoke |
|---|---|---|
| `demo_s1_web` | Source, the poisoned page | `revoked` |
| `demo_s1_summary` | Memory derived from the page | `tainted` |
| `demo_s1_rule` | Memory derived from the summary | `tainted` |
| `demo_s1_edit` | Action, low risk, relied on the rule | `tainted` |
| `demo_s1_commit` | Action, medium risk, relied on the edit | `tainted` |
| `demo_s1_push` | Action, high risk, irreversible, relied on the commit | `tainted` |

The stored blame path for the push, child first, is `demo_s1_push`, `demo_s1_commit`,
`demo_s1_edit`, `demo_s1_rule`, `demo_s1_summary`, `demo_s1_web`.

Say it in this order on camera:

1. The barrier is one query. It revokes only a Source or Memory that is not already revoked, and it creates the running revocation in the same query.

```cypher
MATCH (r:Node) WHERE r.id = $id AND r.status <> 'revoked'
  AND ('Source' IN labels(r) OR 'Memory' IN labels(r))
SET r.status = 'revoked', r.revoked_at = $now, r.reason = $why, r.taint_parent = NULL
WITH r CREATE (v:Node:Revocation {id:$rid, tenant:$tenant, root_id:$id, reason:$why,
    kind:$kind, state:'running', started_at:$now, created_at:$now})
RETURN r.id
```

2. The fixpoint discovers descendants over `FEEDS`, then quarantines members that are still `ok` or `preserved`. It repeats until a discovery finds nothing left to quarantine.

```cypher
UNWIND $ids AS i MATCH (n:Node {id:i}) WHERE n.status IN ['ok','preserved']
SET n.status = 'quarantined' RETURN count(n) AS n
```

3. Python then reads parents and support and writes the final statuses. In this chain every descendant stays tainted, because none has a healthy corroborating source. The explanation stored on each tainted node is `taint_parent`. Blame follows that property until the next parent is missing or the chain repeats. That walk is not capped by `max_depth`. The depth cap belongs to the separate hop-path helper.

```cypher
MATCH (n:Node {id:$id}) RETURN n.taint_parent
```

**Decision (ADR-006):** `:Revocation` carries `state` (running/done), not `status` - a revocation
is not a belief, and crash recovery keys on `state`.

## 4. Blame and impact: the two traversals

- **Impact** ("what depends on this?") is `algo.BFS` from the node over `FEEDS` at a bounded depth,
  then one chunked read of node details plus the action details, so the answer groups by type and
  status and flags the irreversible actions individually.
- **Blame** ("where does this come from?") is two traversals: the fast path follows `taint_parent`
  hop by hop to the revoked root (one small query per hop, until the parent is missing or the chain
  repeats). `max_depth` does not cap that walk. The full path fetches
  ancestors over `DERIVED_FROM` plus the edge list and computes a shortest path in Python with
  parent pointers. `blame` on an unknown id returns `not_in_graph` - never an empty success.

```bash
curl -s "$BASE/v1/blame/demo_s1_summary" -H "$H"
curl -s "$BASE/v1/impact/demo_s1_web?max_depth=6" -H "$H"
```

## 5. Preservation: the part that is not a cascade

Two memories derived from the same revoked page, one independently corroborated by a trusted
document, end up `preserved` and its dependents stay `ok`. This is the difference between Pedigree
and a naive cascade, and it is measured: in `evals/REPORT.md` the full-cascade baseline
over-invalidates `0.2777` of the unrelated items in the deepest generated cell while Pedigree
over-invalidates `0.0` and preserves every independently supported belief.

**Decision (ADR-007 / ADR-008):** only a human or scanner assertion counts as trusted support. An
agent can assert `CORROBORATED_BY` with `by='agent'`, and the engine will not let such an edge
overwrite a human attestation - otherwise an injected prompt could launder a poisoned source into
`preserved` (a reproduced attack, see `docs/consults/007-capture-trust/redteam.md`).

## 6. The gate: a deterministic decision over stored labels

`/v1/gate` (and MCP `pedigree_check_action`, and the Claude Code `PreToolUse` hook) takes a
proposed action and its lineage, and answers `allow`, `warn`, `reverify` or `block` with reasons
that carry the path:

1. a relied-on node that is `revoked`, `tainted`, `quarantined`, or `preserved` without trusted
   support -> `block` at medium or high risk, `warn` at low risk. That `warn` becomes `reverify`
   only when the list came from the session read window. An explicit `relied_on` at low risk stays
   `warn`. The reason path is the `taint_parent` chain;
2. a confidentiality tag outside the requested audience -> block;
3. `low_integrity` on an irreversible or high-risk action -> reverify;
4. an unknown id -> reverify (unknown lineage is never "safe");
5. otherwise allow. No lineage at all -> allow with a `no_lineage` warning, because blocking every
   new session would make the tool unusable.

**Decision (ADR-007):** rule 1 keys on the *materialised* status, not on re-walking ancestry. The
revoke engine already resolved containment into `status`, so a preserved belief is not blocked as
tainted, and its `ok` dependent is `allow` at medium risk. Re-deriving ancestry for that rule
would make the preservation feature dead on arrival and put a depth-12 BFS on every hook call.
`low_integrity` is copied from parents at write time and preservation does not clear it. A
high-risk or irreversible check of that same dependent still returns `reverify` with
`untrusted_influence`. The workspace placeholder `git push origin main` is classified that way,
so the seeded S8 branch shows `reverify` there. A `preserved` node whose only support is
agent-asserted is gated as tainted.

```bash
curl -s -X POST "$BASE/v1/gate" -H "$H" -H 'Content-Type: application/json' \
     -d '{"action":{"tool":"Bash","summary":"git push origin main","effect":"irreversible","risk":"high"},
          "relied_on":["demo_s1_summary"]}'
# S8 after revoke: medium risk allows the healthy dependent; high risk still reverifies
curl -s -X POST "$BASE/v1/gate" -H "$H" -H 'Content-Type: application/json' \
     -d '{"action":{"tool":"Edit","summary":"edit the policy","effect":"reversible","risk":"medium"},
          "relied_on":["demo_s8_dependent"]}'
```

`policy.yaml` classifies tool + command text into `effect`/`risk` when the caller does not supply
them (documented regex heuristic, `evals`-independent of any LLM).

## 7. Invariants: the graph's own test suite

`/v1/invariants` runs a family of `count(*)` probes: every `:Node` has a status and an id, the
parent/child mirror is complete, a tainted node has a `taint_parent` that exists and is unhealthy,
a preserved node has a healthy corroborating source, no `ok` node sits under a revoked parent, and
no node carries a foreign tenant. Tests assert the checker both passes on healthy graphs and
**fails** on a hand-corrupted one.

## 8. Multi-tenancy and the ACL pattern

Every graph name comes from `graph_name(tenant)` - the single choke point - and the tenant comes
from the bearer token, never from a body field. Because ids are `[a-z0-9]{3,24}`, the Redis ACL key
pattern `~ped:abc` can never match tenant `abcd`'s graph; `tests/security/test_acl_mechanism.py`
provisions real ACL users scoped to `~ped:<tenant>` and `~ped:<tenant>:wi:*` and proves cross-
namespace denial (including `GRAPH.COPY` into a foreign namespace) on v4.22.1. Wiring those users
into the running service is an open item, stated in the README limitations.

## 9. What to say if a judge asks

- "Isn't this just a cascade delete?" - the traversal is the easy part; capture, preservation,
  the barrier and isolation are where the work was, and each is measured or tested.
- "Why FalkorDB?" - one graph per tenant, `algo.BFS`/`algo.pageRank`, `GRAPH.COPY` for what-if,
  constraints and the ACL pattern. Remove it and the product does not exist.
- "Can a compromised agent lie?" - MCP-reported edges are tagged and weighted lower; hook-captured
  edges are outside the model. A compromised *host* can forge anything, which we state in the
  README limitations.
- "Who decides a source is bad?" - a human, a scanner or an alert; Pedigree handles the
  consequences.
- "Did AI write this?" - assisted, disclosed in `AI_DISCLOSURE.md`; the decisions above are
  recorded in `docs/DECISIONS.md` with their evidence.
