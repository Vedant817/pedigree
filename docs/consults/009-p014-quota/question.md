# P-014 quota admission consult

Read FIX_PROMPT.md C2, docs/fixes/P-014.md, current uncommitted diff in
engine/ingest.py and api/routes/events.py, db/queries.py and registry.py.
Question: smallest correct quota design covering REST/MCP/events/session writes,
idempotent retries and concurrency while preserving standalone engine graphs?

Current unfinished implementation calls TenantRegistry inside three engine writes,
breaks 12 real-DB core tests (unregistered fresh_graph), omits sessions and uses
unlocked count-then-write. Batch preflight counts events rather than new nodes.
Existing event batches are sequential, NOT transactional despite P-014 draft.
Existing revoke.tenant_lock is process-local, not a cross-worker guarantee.

Need concrete implementation recommendation, explicit scope/risks and tests.
No paid providers, no benchmark/mass data. Actual FalkorDB42201, static Cypher.
Independent role consult: write only assigned domain.md/architect.md/specialist.md
here, <=400 words; don't read other answers. Evidence from code or small real DB
experiment if essential; no source edits. Distinguish process vs cross-process
enforcement; don't call count-then-write atomic. Cap metadata/Revocations count
semantics and pre-existing caps must be stated. Don't print tokens.
