# 007 - Capture trust: Senior Architect consult (role-switch, docs/04 §12)

The independent `senior-architect` subagent failed three times with provider errors (rate limit /
504), so this file is written by the orchestrator in the role-switch ritual: every claim below is
either a quote from the specialists' files or a **probe run against local FalkorDB v4.22.1**
(`scratch/probe_identity.py`, fresh throwaway graph, deleted afterwards). No design is asserted
without that evidence.

## Probe results (v4.22.1, measured today)

| Probe | Result |
|---|---|
| `CREATE INDEX FOR (s:Source) ON (s.uri)` + `(s.content_hash)`, indexes OPERATIONAL, then `GRAPH.CONSTRAINT CREATE ... UNIQUE NODE Source PROPERTIES 2 uri content_hash` | **ok** (composite unique constraint is expressible) |
| `MERGE (s:Node:Source {tenant,uri,content_hash}) ON CREATE SET ...` called twice with the same key | same node id, `created_at` unchanged -> **idempotent** (atomic, single query) |
| same `uri`, different `content_hash` | **new version node** (2 nodes total) |
| uri-only unique constraint + same uri with a new hash | **constraint violation** -> a uri-only constraint must NOT be created (it rejects a legitimately changed page) |
| `CREATE` a node with an existing `id` | `Conflict` (the id unique constraint still works) |
| `MERGE` with a null key value | error -> hash-less/uri-less reads cannot use the composite key |

## Recommendation

**Option B - derived identity + structural authority** (the red team's design, evaluated and
amended; the domain researcher's hybrid supplies the authority ordering).

### Problem 1 - stable Source identity
- `record_source` gains a **derived-identity path used only when the caller supplies no explicit
  `id`** (an explicit id keeps naming the node, so `Conflict` on duplicates is unchanged and the
  hook channel must stop forwarding caller ids - that was red-team attack 1).
- Key = `(tenant, uri, content_hash)` when both are present; `(tenant, uri)` when only the uri is
  present (a hash-less read of the same path is the same source); unchanged caller-id/mint path when
  the uri is absent. One atomic `MERGE ... ON CREATE SET` per call, so 200 identical reads still
  make 1 node and a changed page makes a new version node whose old hash stays revocable.
- New per-tenant schema: exact-match indexes on `Source(uri)` and `Source(content_hash)` plus the
  composite unique constraint, created after the indexes are OPERATIONAL, idempotently.

**Rejected:** (A1) caller-supplied stable ids only - the hook cannot mint a stable id without
hashing the artifact itself, and the measured 3-nodes-per-path bug is exactly a caller-id bug.
(A2) uri-only unique constraint - measured to reject changed pages. (A3) lookup-then-create in two
queries - not atomic; two concurrent identical reads would race into two nodes.

### Problem 2 - authority separation
- **Structural rule first (load-bearing):** the agent channel may only *downgrade* (Biba *-property,
  cited in domain.md). `integrity` is removed from `SourceCreate` / the MCP `record_source` schema and
  `by` from `CorroborateRequest` / the MCP `corroborate` schema; the engine always derives them
  (`default_integrity(kind)`, `by='agent'`). A forgotten call site can no longer re-open the hole
  because the parameter is not expressible.
- Agent-safe kinds on the direct channels (REST `/v1/sources`, MCP `record_source`) are limited to
  `web|tool_output|mcp_tool_desc|other`; trusted-by-default kinds (`file`, `rules_file`, `user_prompt`,
  `human`) are assertable only through the capture channel `POST /v1/events`, whose runtime field is
  the channel marker. A forged events payload is the documented residual (docs/01 §9 already lists
  forged hook payloads); it is recorded, not silently accepted.
- **Second credential, additive only:** `PEDIGREE_HUMAN_TOKEN` (operator-held, `.env`, never issued
  to an agent's MCP config). When set, `/v1/corroborate` with a matching `X-Pedigree-Human` header
  writes `by='human'`; anything else writes `by='agent'`. When it is not configured, the operator has
  no way to mint trusted support - fail closed, and KNOWN_ISSUES 11 stays a documented limitation
  rather than being claimed fixed.
- **Write-once-then-upgrade corroboration:** `Q_CORROBORATE` becomes `SET r.by = CASE WHEN r.by IS
  NULL THEN $by WHEN $by IN ['human','scanner'] THEN $by ELSE r.by END`, so an agent edge can be
  upgraded by the human channel but never downgraded (red-team attack 7).
- The UI keeps no authority: it only displays what the graph says (an agent-asserted `preserved` is
  already gated as tainted by ADR-007, so there is nothing for a UI claim to unlock).

**Rejected:** (B1) a second registry tenant token with `role='human'` - the red team's measurement
stands: on a single host it moves "forge a string in a body" to "read a string from a file" the
agent can also read, and it changes the registry schema for no measured gain. (B2) trusting
`via='cite'`/`agent_reported` - measured identical between MCP and genuine citations.

## Invariants / failure modes / reversibility
- I1: on the agent channels, `integrity` is never caller-supplied and `by` is never `human|scanner`.
- I2: two calls with the same `(uri, content_hash)` never create two nodes (test-level).
- I3: the composite unique constraint must never be preceded by a uri-only constraint.
- Failure modes: a hash-less read after a hashed one creates a second node for the same uri
  (documented); pre-existing dev graphs that already contain duplicate `(uri, content_hash)` pairs
  cannot gain the constraint - `ensure_schema` reports it and the limitation is recorded.
- Reversibility: high. Identity is one query pair + schema DDL; authority is schema/route-level
  field removal. Both are additive-or-removable without touching the revoke/blame/gate engines.
