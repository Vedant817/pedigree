# Red-team recommendation

The current gate is bypassable: `ingest.py:124-132` is an unlocked read/check, calls registry/schema setup on engine writes, and charges at least one even for `add=0`. `events.py:43-45` excludes sessions and counts duplicate Source events as new nodes. MCP and REST gate retain independent prechecks. `remember` validates corroborators after creating the memory; events execute sequentially. Quota rejection and general transactional rollback are different requirements.

Smallest bounded implementation: explicit quota policy injected into ingest; standalone graphs remain registry-independent and unlimited unless configured. Public entrypoints must supply the registered policy and verify its tenant/graph binding; never interpret a registry lookup failure as unlimited. Remove interface prechecks. Hold one shared reentrant graph lock across planning, admission, and every write in the request, including session creation, gate recording, and nested engine calls. Plan canonical identities using exactly current source rules: normalized hash + URI, derived URI-only ID only when no explicit ID, otherwise explicit creation semantics. Deduplicate new session IDs; reject conflicting IDs before mutation. Corroboration/READ edges cost zero. Exact source retries at capacity must succeed without changing stored trust.

This is **process-local enforcement**, not DB atomicity. Support one writer process only until stronger admission ships; separate MCP processes/workers invalidate that guarantee. If cross-process enforcement is required now, atomically reserve capacity using a static DB query against durable quota state before graph writes; all writers must participate. Initialize from existing graph counts under writer quiescence. Retain uncertain reservations after crashes/timeouts (fail closed); reconciliation requires writer quiescence. A TTL lock without fencing is insufficient. Separate reservation and graph writes still do not make batches transactional.

Define the cap explicitly. Recommended ingest budget counts Source/Memory/Action/Session/Agent; exempt Revocation recovery records and internal quota metadata, exclude them consistently from counts/invariants, and document this change from current all-node counting. Never block revoke/recovery at intake capacity. Existing over-cap graphs allow zero-growth operations but reject growth; preserve configured caps.

Adversarial acceptance cases:

1. Two synchronized writers compete for one slot; only one creates, including independent processes if claimed supported.
2. Full graph: existing source/session retries and corroboration succeed; new source/session fails.
3. Duplicate sources, aliases, mixed hashes and session events charge exact unique growth.
4. REST, MCP, gate-record, and session-only batches enforce identical limits.
5. Unregistered standalone graphs work; public missing-policy and graph-mismatch requests fail closed.
6. Over-cap batch returns 429 with no writes; injected later validation/DB errors demonstrate documented partial-write behavior, never fictional rollback.
