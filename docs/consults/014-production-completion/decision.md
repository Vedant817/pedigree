# Production completion decision

Preserve the existing crashed volume. Build and test each change against separate
owned databases. Token-derived tenant graph namespaces and the privileged registry
remain compatible. Tenant operations use database ACL identities with a dedicated
deployment secret, exact graph namespaces and scoped quota mutex access; failures
never fall back to privileged credentials.

Capture envelopes must persist before delivery, with idempotent replay and no stored
bearer material. Offline gates deny rather than replay stale approvals. Restore is
an explicitly offline operator operation with recoverable journal and rollback,
not an online delete-and-copy sequence. Atomic replacement needs a real DB probe.

Default Compose starts empty with authenticated durable storage. Synthetic scenarios
remain available only in an explicitly named local demo configuration. Production
rejects demo flags before seeding or serving. Render configuration declares persistent
storage and an always-on API. Live billing changes remain user-owned after the user
chose local continuation. No hosted persistence or automated-testing pass is inferred
from configuration.

Acceptance: empty first boot, authenticated API capture of repository artifacts,
restart survival, two-tenant REST/MCP isolation plus raw DB denial, offline spool
and lost-ack replay, checkpoint/failure recovery, local gates and independent review.
Consult responses identify these tests; they do not constitute executed evidence.
