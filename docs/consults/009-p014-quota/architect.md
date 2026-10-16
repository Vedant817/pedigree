# Architect recommendation

The current patch is neither atomic nor compatible with standalone graphs: `enforce_quota` constructs the API registry inside engine calls and performs an unlocked read followed by a separate write. REST/MCP also reject deduplicated source retries before the engine can resolve identity.

**Smallest coherent repair:** inject an optional admission policy/cap into the engine; standalone calls default to uncapped and never instantiate TenantRegistry. Authenticated REST, MCP, events, and session endpoints must pass the registered cap through one shared service wrapper. Remove their independent count gates. Cover Source, Memory, Action, Session and actual Revocation creates; corroboration and READ create edges only and require no node allowance.

For bounded single-writer deployment, hold the same tenant RLock across admission and every write in the request, including revoke/reinstate. Events remain sequential: normalize, resolve existing source/session identities and duplicates within the batch, compute exact prospective node additions, reject over-budget before the first mutation, then execute while holding that lock. Do not describe this as transactional: subsequent validation/DB failures can leave earlier events committed. The existing draft's transactional assertion must be corrected.

**Concurrency boundary:** this wrapper only coordinates one process. HTTP workers and a separately running MCP server bypass each other's locks. Do not mark cross-worker P-014 complete from threaded tests. For cross-worker cap enforcement, put the count predicate and conditional CREATE in each existing static graph write query, with existing-identity lookup returning before quota rejection. Prove FalkorDB42201 behavior with independent clients. Per-create atomicity still cannot guarantee a whole events batch rejects without partial writes: that stronger contract requires an atomic database batch implementation or a proven cross-process request serializer. A bare Redis lease is insufficient without fencing. This is additional scope, not a property of the proposed RLock.

Keep current `node_count` semantics (`MATCH (n)`), including Session/Revocation; new metadata would consume capacity unless explicitly excluded everywhere. Preserve registry caps; do not raise caps or delete existing data. Above-cap tenants may perform zero-addition operations, but no new nodes. Reject a capped revocation before changing root status if its ledger node cannot fit; document this safety tradeoff.

Tests: standalone regression; REST/MCP parity; session ensure/read ensure; full-cap source/session retries; same-batch dedupe and aliases; exact-fit/overflow unchanged graph; Revocation boundary; independent-process races. Explicit Memory/Action IDs currently conflict on retry: preserve that contract unless separately implementing payload-checked idempotency.

## Addendum: cross-process serializer (194 words)

A non-expiring owner-token Redis mutex is the smallest defensible cross-process option **under explicit operational assumptions**. `SET key token NX`, bounded acquisition, then hold through cap lookup, exact source/session-aware batch planning and all synchronous writes. Release by atomic token comparison plus DEL. All public creators, including revoke/reinstate and separate MCP processes, must cooperate; standalone calls stay uncapped. Nested engine calls reuse admission context rather than reacquire. Lock keys must include the complete graph identity.

No expiry removes the usual lease-expiration fencing race: a paused owner cannot lose ownership merely because time passes. Crashes sacrifice availability, leaving the tenant blocked. Nevertheless “finally release” is unsafe following an uncertain write outcome: connection loss can leave GRAPH.QUERY executing after the client returns. Preserve/poison the mutex on ambiguous mutation errors; recover only after stopping all writers and proving graph work has quiesced.

Redis key eviction, FLUSH, restart losing locks, or asynchronous failover can also invalidate ownership while the old owner runs. Require non-evicting durable single-primary operation, coordinated restart, and explicit recovery; otherwise fencing is still necessary. Operator deletion while writers run is forbidden.

Accept this as documented constrained-deployment enforcement, with independent-process serialization/crash tests. It does not provide transactional rollback for subsequent validation/database errors or general fault-tolerant distributed locking.
