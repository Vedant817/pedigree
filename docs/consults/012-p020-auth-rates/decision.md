# Decision: live indexed authority and one admission service

Use the domain's single static OR query over three operational exact-match digest
indexes. Resolve stored role/prefix/status on every lookup, reject ambiguous tenant
candidates and remove the authority cache/tenant scan. Keep invalidate_cache as a
compatibility no-op if callers need it. Nullable legacy digests remain agent-only;
no startup dictionary, plaintext token storage or stale authority. Indexed lookup
is bounded query work, not a mathematical constant-time or production latency promise.

One locked per-instance limiter is injected into REST and its mounted MCP server;
standalone MCP owns one equivalent instance. Authentication resolves identity; shared
operation admission occurs once after shape/permission checks and before protected
graph work. Remove old duplicate loops. Tenant buckets are shared across roles and
protocols. A batch is one request; nested engine calls do not charge again.

Choose architect classification: reads have their own sliding-minute budget, equal
to the existing write budget. GET/report/blame/audit and gate(record=false) are reads.
Events/ingest/sessions/corroboration, gate(record=true), and what-if are writes.
Real revoke/reinstate are writes plus the additional destructive-operation bucket;
their dry runs are reads plus that bucket. Rejected permissions/validation consume
no tenant budget. An admitted engine failure consumes its admission. All applicable
buckets reserve atomically; rejected reservations consume none. Return Retry-After
for REST rate failures and bounded retry details for MCP tool errors.

Failure backoff counts actual unauthorized outcomes per real transport peer: allow
the stated first failures, then reject before lookup until expiry. Concurrent work
already in flight is not a hard bound on authentication lookup work. Ignore caller
forwarding headers and disable Uvicorn proxy rewriting in shipped entry points;
custom proxy deployments must explicitly retain a trustworthy peer boundary. Stdio
uses one server-local scope, never caller-supplied identity. Shared-IP blocking can
temporarily deny valid users behind the same NAT; disclose that chosen tradeoff.
Cover tenant REST/MCP authentication; deployment-admin endpoints should use the same
peer backoff boundary where practical, without granting tenant operator global rights.

Bound keys and sample deques, prune expired state and fail closed on active-key
capacity exhaustion. Never evict an exhausted live key into a fresh allowance.
Clock injection supports deterministic expiry tests; lock protects concurrent N/N+1
and multi-bucket reservation. Limits are per instance and multiply across workers
or restarts; no Redis/distributed rate-limit claim.

No unresolved consultant disagreement on authority or state safety. Domain proved
OR/equality indexed plans, nullable slots and duplicate candidates on 42201; its
local timings are acceptance evidence only. Tests must prove bounded lookup counts
and live cross-process rotation/revocation; exact write/read/revoke boundaries,
concurrent outcomes, mixed REST/MCP budgets, failed-auth threshold/expiry/forwarded
spoofing and bounded state. Independent QA/red-team/full checks required before closure.
