# Decision: ship an explicitly enabled read-only adapter slice

All three independent consultants chose A. Implement the genuine read contract;
do not invent write/edit/shell mappings. The single subsequent native-write probe
was rejected by the free provider (HTTP 403, zero tool hooks). Its note is separate
evidence, not a write fixture. No paid fallback or additional attempt is authorized
by this decision.

The plugin is disabled unless PEDIGREE_OPENCODE_ENABLED=1. When enabled, it accepts
only the observed native read tool. It denies every other tool before execution,
including MCP, write, edit and shell. Thus this is a read-only capture/inspection
mode, not the complete coding-agent adapter. F-08 stays implementing; native
acceptance beyond the old observation fixture remains unverified/provider-blocked.

Use the actual GateRequest and EventsPayload. Derive identity only from runtime
session/call fields, namespace by canonical project, and ignore model-supplied
tenant, risk, audience and dependency fields. Gate every read; block/reverify,
unavailable/malformed responses and capture uncertainty deny further operations.
No approval/ask flow is claimed. A completed read whose capture fails is reported
as completed-but-uncaptured, never as a prevented tool execution.

Validate real paths within the canonical project, exclude credential paths, bind
before/after calls and reject ambiguous display metadata. Hash a versioned
descriptor of observed display text/range/truncation in a distinct project-relative
read-view URI. Do not read filesystem bodies after the fact; do not call whole-file
artifact lookup or claim file-byte identity/cross-session write linkage. No bodies,
outputs, commands, previews, absolute paths, tokens or exception details in telemetry.
Use bearer agent credentials only, HTTPS outside loopback, no redirects, bounded
requests/responses and timeouts.

Serialize capture acknowledgements and gate calls per session; track in-flight and
acknowledged call IDs with bounded memory. Ambiguous/failed capture latches the
session incomplete. No transparent retry of a sequential non-atomic event batch.
Durable replay/ack ledgers remain F-22, not silently invented here: restarting may
lose deduplication/gap state, but this slice still unconditionally denies all
side-effecting/unsupported tools. That explicit restriction is why this smaller
slice does not depend on persistent approval state for its enforcement claim.

Tests: first-red builtin Node tests against genuine fixture; injected transport
failures and execution spies; real API+FalkorDB persisted read-view/window proof;
independent QA/red-team with credential/privacy/path/ordering/denial cases. Node 24
can execute erasable TypeScript without npm downloads. Do not turn hook replay into
installed-runtime proof. Reversible: opt-in plugin only; no engine/schema change.
