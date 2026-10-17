# Architect recommendation

Choose indexed persisted lookup, not a startup digest dictionary. `registry.py:130-155`
currently scans `list_tenants()` on misses; cache hits already reread live authority.
Add three nullable-slot exact-match indexes and static parameterized lookup branches
in `queries.py`; require domain EXPLAIN evidence that each branch uses its index.
Reuse `_principal` (`registry.py:160-176`) for stored digest, active status, complete
expected token prefix and legacy-agent semantics. Deduplicate rows; ambiguous matches
fail closed. Remove the authority cache: it saves no necessary DB read and creates
unbounded process state. Keep `TenantRecord` APIs separate. Indexed lookup means
bounded probes, not a guaranteed mathematical O(1) database latency claim.

One injected admission service owns all rate state, shared by REST and mounted MCP;
standalone MCP owns one equivalent instance. Authentication resolves identity only.
Explicit route/tool adapters classify once after valid shape/auth/authorization and
before engine/schema work; nested engine operations never charge again. Remove both
existing loops: `auth.py:_gate_rate` and `routes/engine.py:40-49` currently duplicate
charges. MCP `_resolve` (`mcp_server.py:197-232`) currently has no admission owner.

Use tenant-scoped, role-shared 60-second sliding buckets: read=120, write=120;
revoke/reinstate additionally use a 10-call destructive-operation bucket, including
dry runs. GETs, gate(record=false), dry runs and report/blame/audit are reads;
gate(record=true), events, sessions, corroboration and what-if are writes. What-if
consumes scratch work despite leaving primary data unchanged. Count admitted engine
failures; validation/permission failures consume neither tenant bucket. One request,
including a batch, is one admission. Reserve all applicable buckets atomically under
one lock; rejected requests consume none. Exactly N admissions succeed; N+1 receives
429 and Retry-After derived from the oldest blocking sample.

Bound keys and deque lengths, prune expired buckets, and fail closed when active-key
capacity is exhausted; eviction must not reset live limits. Inject monotonic clock
for deterministic boundary/race tests. Limits remain per instance, not distributed.
Failed-auth peer admission allows ten failures then blocks the next attempt before
lookup until expiry. Ignore forwarding headers and disable server proxy rewriting;
HTTP peer and bounded local stdio scope are distinct. This intentionally can deny a
valid caller sharing a blocked IP; document that tradeoff.

Acceptance: two-process rotation/revocation, legacy nullable slots, concurrent N+1,
read/write independence, REST/MCP combined counts, dry-run/what-if classification,
spoofed headers, shared-IP expiry and capacity exhaustion. Confidence: high in ownership
recommendation; index plans and runtime integration remain unproven until measured.
