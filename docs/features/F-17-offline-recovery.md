# Offline tenant checkpoints and recovery

Acceptance: a deployment administrator stops every service/MCP/direct writer before
using `pedigree checkpoint`; each mutation requires `--writers-stopped`. Tenant ids
are validated and must exist. No HTTP/MCP restore endpoint is introduced.

Named checkpoints are immutable GRAPH.COPY snapshots, with at most twenty retained
snapshots per tenant including restore rollback snapshots. Listing returns only the
selected tenant's metadata. Explicit drop frees capacity. Restore retains the previous
main graph as a rollback checkpoint and atomically renames a verified staged copy.
A Redis journal reserves the tenant maintenance operation before mutation. An
interruption blocks further mutations until explicit recovery completes or rolls back
the restore. AOF and WAITAOF local fsync are required; persistence failures never
discard the journal or rollback graph. This is offline maintenance, not online safety.

Tests: real DB copy/rename and identity/edge equality; duplicate/invalid names; cap;
copy failure; rename acknowledgement loss; process death with a pending journal;
rollback; fsync failure; authorization and stopped-writer acknowledgement.

ADR draft: Consult 014 chose offline restore because online reader/writer exclusion
is not implemented across transports. Fresh FalkorDB 4.22.1 accepted
RENAME of a graph and RENAME over an existing graph; subsequent graph query and copy
worked. Keep immutable rollback graph until explicitly dropped. No MULTI/EXEC.
The deployment admin DB credential is required, like existing offline bootstrap;
PEDIGREE_ADMIN_TOKEN must be nonempty and nondefault even in development. The CLI
does not authenticate an untrusted remote caller: access to deployment environment
and administrator DB credentials is the administrative boundary.

Usage, with deployment environment loaded (never put credentials in arguments):

```sh
pedigree checkpoint create --tenant acme --name before-upgrade --writers-stopped
pedigree checkpoint list --tenant acme
pedigree checkpoint restore --tenant acme --name before-upgrade --writers-stopped
pedigree checkpoint status --tenant acme
pedigree checkpoint recover --tenant acme --writers-stopped
pedigree checkpoint recover --tenant acme --rollback --writers-stopped
pedigree checkpoint drop --tenant acme --name before-upgrade --writers-stopped
```

Keep writers stopped after ANY error until `status` reports no pending journal and
graph invariants pass. `recover` resumes the recorded operation; `--rollback`
selects the retained pre-restore graph instead. Backups appear as `rollback-*` in
listing. Capacity includes these backups; explicitly drop an old snapshot to free
space. Never restore concurrently with a second maintenance process. The journal
rejects new operations, but recovering a live operation is operator misuse.

This restores lineage graph state only: registry credentials, Redis quota mutexes and filesystem content are not rewound.
Capture delivery receipts ARE tenant graph nodes and rewind with the graph, including
their delivery cursors and action fingerprints. Stop hook replay during maintenance;
reconcile external spools and deliveries acknowledged since the checkpoint before
resuming collection, because replay can recreate removed events. Graph snapshots are on the same DB,
so a separate off-host database backup is still necessary for disk-loss recovery.
FalkorDB can reject GRAPH.COPY when it cannot fork (observed while overlapping
independent test runs). Treat that as unavailable, retain the journal, and recover
after resource contention is resolved; do not remove the backup or retry by deletion.

A missing main graph can be restored from a healthy checkpoint. Its journal records
that no previous main existed; `recover --rollback` refuses to delete the newly
restored graph to recreate absence. Resume that operation with ordinary `recover`.
An unhealthy existing main is retained with matching graph content as a forensic rollback snapshot;
the chosen restored checkpoint must still pass invariants before reopening writers.

Stranded quota mutex recovery is a separate explicit operator decision. Stop every
API, MCP, hook replay and direct engine writer; confirm no DB query remains in flight
(a client timeout is not proof of quiescence). Complete any pending restore first.
Then inspect and deliberately release only the selected tenant's mutex:

```sh
pedigree checkpoint mutex-status --tenant acme
pedigree checkpoint release-mutex --tenant acme --writers-stopped --confirm-mutex-release
```

The owner token is never printed. Release uses owner-token compare-and-delete with
local AOF fsync; a changed owner rejects the release. Nothing automatically expires
or removes the mutex. Do not resume writers until graph invariants and journal status
are healthy. Removing a lock while a writer remains active violates quota safety.

A selected `recover --rollback` direction is journaled durably before replacement.
After another interruption, plain `recover` continues that rollback choice. An unhealthy
forensic backup is retained for inspection but cannot be reopened via rollback until
its invariants pass.

Pinned-engine persistence preflight: complete a fresh database-wide BGREWRITEAOF
before reserving maintenance and before recovering a pending operation. The
v4.22.1 test instance replayed schema effects for an already-deleted historical
graph and exited 139 on a subsequent restart. Compacting the current graph state
under stopped writers removes that historical replay dependency. Wait for the
rewrite generation to finish successfully (bounded to sixty seconds) before
GRAPH.COPY; rewrite failure or timeout keeps writers stopped and the journal intact.
This adds global fork/disk cost and requires administrator BGREWRITEAOF/INFO access.
It is a recovery-path mitigation, not a general fix for engine persistence bugs.
