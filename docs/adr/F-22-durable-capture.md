# ADR F-22 | 2026-10-18 | Durable capture delivery

Context: a one-second hook network failure previously lost capture and allowed an
unchecked action. Retrying the existing sequential event endpoint could duplicate
Actions after partial application or response loss.

Decision: the CLI constructs sanitized immutable events without network access,
including deferred artifact producer lookup, and commits them to a bounded SQLite
outbox before delivery. A separate SQLite transaction supplies the interprocess replay
lock without blocking enqueue during HTTP waits. The namespace is SHA-256 of endpoint
and credential; credentials remain environment-only. File data, prompts and shell
arguments are excluded; durable Bash metadata is conservative high risk/unknown effect.
Raw URL/path metadata remains user data and requires private local storage.

The backwards-compatible optional /v1/events delivery_id selects resumable delivery:
first event must ensure the single session; allowed operations are sessions, hashed
sources, reads and actions. A CaptureReceipt metadata node stores the immutable
payload digest, cursor, resolved artifact lookup plans, canonical aliases and response.
These nodes are indexed, carry tenant/id, count against quota, and are explicitly
validated separately from lineage Node invariants. Receipt changes and writes share
the existing tenant quota mutex. Nodes are never silently deleted or expired.
Action creation atomically includes its deterministic server ID and capture fingerprint;
if progress acknowledgement was interrupted, replay finds that exact creation, repairs
the idempotent session READ and advances. Source identity already converges on URI/hash.
READ timestamps only advance, so retries cannot move an old observation ahead of a
newer observation. Producer lookup choice is persisted before proceeding and stays
fixed through replay. Delivery identifiers cannot be reused with different payloads.

No gate decision is persisted or reused. Pre-tool invocation drains the queue and
requires a fresh online gate; storage, parsing, connectivity or backlog failures emit
a deny decision. Capture-only failures warn and return nonzero, retaining queued data.

Consequences: a service older than this delivery contract cannot acknowledge queue
entries. The operator must upgrade before replay. Each namespace retains at most
1000 items/8 MiB payload; SQLite data pages are capped at 4096, plus journal overhead.
Receipt retention consumes tenant quota; exhaustion denies further capture. The
stable-primary/nonexpiring-mutex contract remains: ambiguous DB failures may strand
admission and require quiescent operator recovery. Replay does not clear locks.
SQLite durability assumes a durable local filesystem; destructive host/data loss and
multi-host shared-filesystem locking are not established. Windows uses inherited
account ACLs; POSIX files are created with mode 0600. Token rotation cannot drain an
old namespace with a new token: retain the original authorized agent credential to
replay it, or explicitly archive the old evidence offline.

Evidence: tests/unit/test_capture_spool.py, tests/integration/test_capture_delivery.py.
Tests cover real DB writes, partial commits, acknowledgement loss, invariant checks,
interprocess replay and a real hook subprocess with an offline/restarted HTTP service.
These are synthetic contract inputs, not installed Claude runtime execution. Hosted
preview, independent QA/red-team and third-party PR evidence remain separate gates.
