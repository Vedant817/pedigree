# ADR draft: Offline checkpoint recovery

Status: implementation proposal with local evidence; independent QA pending.

Consult 014 selects deployment-local maintenance. The operator must stop every API,
MCP, hook replay and direct engine writer and ensure no DB work is in flight before
acknowledging `--writers-stopped`. This acknowledgement is not a distributed lock.
No public HTTP/MCP contract changes. Deployment environment and privileged DB
credentials remain the administrative boundary; CLI requires a nondefault admin token.

Use capped immutable GRAPH.COPY snapshots in the tenant checkpoint namespace. A
Redis SET NX journal reserves maintenance, with a random operation identity. Each
mutation and WAITAOF local acknowledgement use the same connection via a
nontransactional pipeline. Require AOF; never use MULTI/EXEC. Pending journals do
not expire. Keep writers stopped after any failure; recover rechecks recorded graph
fingerprints and invariants before replacement and before clearing the journal.

Restore copies the existing main into a retained rollback graph (including unhealthy
content for forensic inspection), verifies the desired snapshot, copies to a stage,
then uses Redis RENAME over main. The earlier absent GRAPH.RENAME command is
irrelevant to Redis RENAME. Missing main is supported without manufacturing an empty
rollback. Unhealthy forensic backups cannot be reopened until invariants pass.
Persist an explicit rollback direction before replacement so another interruption
cannot silently change that decision. Snapshot content verification is bounded by
node/edge caps and SHA-256 of canonical node/edge rows; this is not a disk backup.

Restore rewinds CaptureReceipt nodes, cursors and action fingerprints alongside
lineage. Registry credentials, filesystem content and Redis quota mutexes remain
outside the graph. Operators must reconcile external acknowledged deliveries and
spools before replay; removed events can otherwise be recreated. Stranded mutex
release is explicit, owner-token conditional and durably acknowledged.

Rejected: delete-main/copy replacement (data-loss gap); online restore without
cross-transport exclusion; automatic journal or mutex expiry; claiming same-host
snapshots protect against disk loss. Local crash/AOF and command evidence are in
`docs/qa/F-17-offline-recovery-local.md`. Hosted verification and independent review
remain separate release gates.

Pinned-engine persistence preflight: complete a fresh database-wide BGREWRITEAOF
before reserving maintenance and before recovering a pending operation. The
v4.22.1 test instance replayed schema effects for an already-deleted historical
graph and exited 139 on a subsequent restart. Compacting the current graph state
under stopped writers removes that historical replay dependency. Wait for the
rewrite generation to finish successfully (bounded to sixty seconds) before
GRAPH.COPY; rewrite failure or timeout keeps writers stopped and the journal intact.
This adds global fork/disk cost and requires administrator BGREWRITEAOF/INFO access.
It is a recovery-path mitigation, not a general fix for engine persistence bugs.
