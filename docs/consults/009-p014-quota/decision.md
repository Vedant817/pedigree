# Decision: explicit request admission, shared across service processes

The interrupted engine patch is not safe: registry dependency breaks standalone
graphs, sessions escape the cap, retries are charged incorrectly and count-then-write
races. Domain probe on FalkorDB42201 observed cap-one admission grow to four nodes;
an explicit write barrier fixed that probe, not an entire sequential events request.

Use explicit admission policy injected by authenticated public entrypoints. Trusted
standalone engine callers remain registry-independent unless supplied a policy.
Remove independent REST/MCP count gates. One engine admission context protects a
request's identity-aware planning, cap check and all creates, with nested operations
reusing the context. Public callers may never fall back to uncapped on lookup failure.
Keep existing node_count semantics including Sessions and Revocations; edges alone
need no node slots. Reject over-cap before mutations; permit zero-growth retries.

Cross-process coordination uses an owner-token Redis mutex with NO expiry, bounded
acquisition wait and token-checked release. This is deliberately not a lease: a paused
writer cannot outlive an expiry and race a replacement. Retain/poison ownership after
ambiguous DB mutation failures rather than releasing while work might still execute.
No automatic lock stealing. Crash recovery requires writers stopped and DB work
quiescent before an operator removes the exact tenant key. Locks contain opaque tokens,
not credentials. Test independent worker processes, not just shared Python locks.

Supported coordination assumptions: one stable Redis/Falkor primary, no eviction of
coordination keys, all public creators use this boundary. Redis restart/failover/key
loss while workers remain active requires coordinated shutdown/recovery; this is not
a distributed failover guarantee. Document that limitation and stranded-lock availability
tradeoff. Existing shared DB credentials can access these keys; future tenant ACL
wiring must explicitly account for the coordination namespace.

Event preflight counts actual new canonical Source identities, explicit new nodes and
distinct Sessions, including duplicates within the batch and existing graph identities.
Quota rejection guarantees no batch writes. Other invalid-input/DB failures may leave
earlier events: do not call sequential event ingestion transactional. Preserve caps
and existing data. Mutation paths that create a Revocation need admission before root
state changes; what-if scratch graphs have separate existing simulation bounds.

Acceptance: existing standalone core tests, exact-fit/overflow snapshot equality,
source/session zero-growth retries at cap, session-only batches, mixed dedupe/aliases,
REST/MCP/gate-record parity, independent-process races, owner-only unlock and ambiguous
write failure behavior. QA/red-team must independently reproduce and qualify scope.
