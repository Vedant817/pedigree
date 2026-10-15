# F-04 - Blame (why does the agent believe X?) + Impact (what depends on X?)

Status: spec | Tests: to be written (failing first) | QA: pending

## Behaviour

### `blame(db, gname, node_id, max_depth=12)` - read-only
1. Node must exist, else typed `NotFoundInGraph` (never an empty result - docs/01 §8 honesty).
2. **Fast path (taint):** if the node has `taint_parent`, follow the pointer chain
   (`MATCH (n:Node {id:$i}) RETURN n.taint_parent`) to the revoked root and include it as a
   root with `path` = that chain. Answers "what did this get tainted by, in one hop step".
3. **Full path (support):** fetch ancestors via `Q_ANCESTORS` (algo.BFS over `DERIVED_FROM`,
   `$depth` parameter, default 12, `-1` = unbounded) then the edge list
   `UNWIND $ids AS i MATCH (c:Node {id:i})-[d:DERIVED_FROM]->(p:Node) RETURN c.id, p.id, d.rel, d.via`.
   Compute BFS parent pointers in Python -> shortest path from `node_id` to **each Source**
   and to **each revoked/untrusted root** (`low_integrity = true`).
4. `max_depth` clamp: integer, `>= 1`; values above the cap are clamped and `truncated=true`
   is set when the BFS frontier was non-empty at the limit. Validated (`InvalidArgument`).
5. Returns `{node: {id, labels, status}, roots: [{id, kind, status, path: [ids]}],
   graph: {nodes: [...], edges: [...]}, truncated: bool}` - `path[0] == node_id`,
   `path[-1] == root id`.
6. All queries `ro_query` with timeouts; no writes.

### `impact(db, gname, node_id, max_depth=12)` - read-only
1. Node must exist, else `NotFoundInGraph`.
2. Descendants via `Q_DESCENDANTS` (algo.BFS over mirrored `FEEDS`, `$depth`), grouped by
   label (Source/Memory/Action/Node) and by status.
3. Irreversible actions (`effect='irreversible'`) are flagged individually;
   `actions: [{id, tool, summary, effect, risk, artifacts}]`.
4. Returns `{node, counts: {by_label: {...}, by_status: {...}}, actions, truncated}`.

## Data model / Cypher touched
- `Q_ANCESTORS`, `Q_DESCENDANTS` (both `algo.BFS` with `$depth` parameter),
  `Q_ANCESTOR_EDGES` (new), `Q_TAINT_PARENT` (new), `Q_ACTION_DETAILS` (exists).

## Invariants
- `blame` and `impact` never mutate the graph (verified by node/property snapshot before/after
  in tests).
- Sum of impact descendants == count from an independent BFS (QA probe).
- A `tainted` node's blame fast-path chain is exactly `taint_parent`-linked and ends at a
  `revoked` root.

## Acceptance tests (to write first, expected to fail)
- `tests/unit/test_blame.py`: BFS shortest-path parent-pointer logic on synthetic graphs
  (diamond, multiple roots, unreachable root, depth truncation); clamp/validation errors.
- `tests/integration/test_blame_impact.py` (real FalkorDB):
  - core scenario: `blame("a_push")` contains the path
    `a_push -> m6 -> m3 -> m1 -> s_web` and root `s_web` (revoked);
  - `blame("m2")` (preserved) lists corroborating Source `s_doc` as a root with an untrusted
    root `s_web` also present;
  - `blame("ghost")` -> `NotFoundInGraph`;
  - `impact("s_web")` groups exactly {m1 tainted, m2 preserved, m3 tainted, m4 ok, m5 ok,
    m6 tainted, a_commit tainted, a_push tainted} and flags `a_push` irreversible;
  - read-only proof: statuses/`Revocation` counts unchanged after both calls.

## Security notes
- Parameterised Cypher only; depth is an int parameter, never interpolated.
- `not_in_graph` for unknown ids (docs/01 §8: never "no impact").
- Output size caps for `graph.nodes/edges` (documented limit, e.g. 2000 each, with
  `truncated=true`).

## Evidence needed
- pytest output for unit + integration; QA independent BFS count comparison; read-only proof.
