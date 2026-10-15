# F-11 gate rule 1 - Senior Architect consult `006-gate-ancestor-scope`

ADR-007: gate rule 1 reads **materialised containment** (node `status` + `taint_parent`), not literal ancestry - a relied node fires `tainted_ancestor` only when its own status is `revoked|tainted|quarantined`; `preserved` and `ok` are clean, and the reason's `path` is the `taint_parent` chain to the revoked root.

## Recommendation
Option B. `compute_final` (engine/compute.py) already resolves transitive containment in topological order - §6.3: "a node whose only bad parent became `preserved` is simply `ok`". The gate consumes that decision instead of re-deriving it: one chunked node read, then a `taint_parent` walk only for nodes that actually fired. No BFS on the hook hot path.

## Why
- Single source of truth: re-deriving ancestry at the gate double-counts what the engine already decided, and makes `preserved` meaningless at the only place the user feels it.
- S8 (docs/03 §5): the dependent of a `preserved` memory stays `ok`; under (A) the gate still warns/blocks it, contradicting the expected verdicts in the same scenario file and the 1:30-2:00 demo claim.
- E3b friction: the read window over-approximates (K=50). Under (A) any session that ever read a later-revoked file flags every later action - friction ~1 on benign sessions; a gate that cries wolf gets disabled, which is the real security failure.
- FalkorDB fit: (A) needs `Q_ANCESTORS` BFS (depth 12) per relied id per PreToolUse call (10 s hook budget, fail-open). (B) is one read query on the allow path.
- Residual risk of (B) is already covered: a `preserved` node from an untrusted source carries `low_integrity=true` (OR over parents at ingest), so rule 3 gives `reverify` on irreversible/high-risk actions; rule 4 gives `reverify` on unknown ids.

## Options
- A (literal transitive ancestors via `Q_ANCESTORS`): rejected - double-counts containment, contradicts S8 and the preservation claim, maximises E3b friction, adds per-call BFS on the hook path; the extra "safety" is noise, not danger it uniquely catches.
- B (materialised status + `taint_parent`): **recommended**.
- Hybrid (B + ancestor BFS only for irreversible/high risk): rejected - rule 3 already reverifies exactly that case (`low_integrity` + irreversible/high); the hybrid duplicates it and pays the BFS on the slowest path.

## Design
`check_action` (read-only, no writes):
1. ids = explicit `relied_on`, else session read window (last K=50 READ targets); none at all -> `allow` + `warning:no_lineage`.
2. ONE chunked read (<=2000 ids): extend `Q_GATE_NODES` to also return `conf_eff`, `taint_parent` (pattern exists in `Q_NODE_DETAILS`). Missing ids -> rule 4 `reverify` [`not_in_graph`].
3. Rule 1 (this ADR): each found id with `status IN ['revoked','tainted','quarantined']` -> `block` if `risk IN ['medium','high']` else `warn`, code `tainted_ancestor`. `path` = `[relied_id, taint_parent, ...]` walked via `Q_TAINT_PARENT` (batched, cap 12 hops) until a `revoked` node or null; a directly revoked relied node gives `path=[id]`; null `taint_parent` on a tainted node gives `path=[id]` + detail `taint_parent missing` (still blocks).
4. Rule 2 confidentiality: union `conf_eff` over relied ids; any tag not in `audience` -> `block` [`confidentiality_violation`].
5. Rule 3: `low_integrity` and (`effect='irreversible'` or `risk='high'`) -> `reverify` [`untrusted_influence`].
First match wins for the verdict; `reasons[]` carries every fired rule. Query order: step 2 always; step 3's walk only when rule 1 fires - the allow path is exactly one read.

## Tests smallest first
1. `gate_preserved_dependent_allows` (THE distinguisher): S8 shape - bad source, M1 corroborated -> `preserved`, M2 derived from M1 -> `ok`; action relies on M2, risk=high -> `allow` (A would block).
2. `gate_tainted_medium_blocks`: relies on tainted memory, risk=medium -> `block`, code `tainted_ancestor`, `path=[M, ..., revoked_source]`.
3. `gate_tainted_low_warns`: risk=low -> `warn` (allow + reason).
4. `gate_quarantined_midflight_blocks`: race hook during revoke, child born `quarantined` -> `block` although compute_final would later say ok/preserved (fail-safe).
5. `gate_revoked_source_direct`: relied id is the revoked source -> block/warn by risk, `path=[source_id]`.
6. `gate_preserved_irreversible_reverify`: preserved + low_integrity + irreversible -> rule 3 `reverify` (proves the backstop, not rule 1).
7. `gate_no_ancestor_traversal`: trace shows no `algo.BFS`/`Q_ANCESTORS` op during check_action.
8. `inv_ok_node_has_no_bad_parent` (new `check_invariants` entry): `MATCH (c:Node {status:'ok'})-[:DERIVED_FROM]->(p:Node) WHERE p.status IN ['revoked','tainted','quarantined'] RETURN count(c)` == 0 after every scenario.

## Invariants
- I1: rule 1's verdict is a function of the relied node's materialised status only; ancestry is used solely to build `path`.
- I2 (load-bearing for B): post-resolve, no `ok` node has a DERIVED_FROM parent with status revoked|tainted|quarantined; `preserved` => >=1 healthy CORROBORATED_BY (already checked).
- I3: any `quarantined` node (revocation running/crashed) blocks - the gate never fails open on unresolved containment.
- I4: risk mapping is exactly block iff risk in {medium,high}, else warn; verdict order allow<warn<reverify<block, first match wins.
- I5: gate performs no writes and reads only `graph_name(tenant)`; `path` <= 12 hops, ending at a revoked node or a documented null.

## Failure modes
Revocation running/crashed -> nodes stay `quarantined` -> block until `resume_incomplete()` finishes. Missing `taint_parent` on a tainted node (invariant violation) -> still block, `path=[id]`. Forged corroboration via MCP (`via:agent_reported`) -> wrongly `preserved` -> allowed; accepted residual, backstopped by rule 3, documented in §9. DB slow -> read timeout -> 503/504, hooks fail-open per deployment config.

## Risks
B is only as sound as `compute_final` + the ingest barrier: a bug leaving an `ok` node under a revoked parent would silently pass the gate. Mitigation: invariant I2 in `check_invariants`, run after every E3 scenario and in CI. Spec §6.6 rule 1 still says "or ancestor" - annotate it with this ADR so implementers do not re-litigate.

## Reversibility
High: the gate is read-only; switching to (A) later = add a `Q_ANCESTORS` BFS per relied id before rule 1 (one function, no schema/engine/Cypher changes; statuses and `taint_parent` are stored either way).
