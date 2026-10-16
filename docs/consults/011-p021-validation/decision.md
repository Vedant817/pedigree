# Decision: validate complete batches and contain SDK errors

Choose raw allowed-field/type checks, documented alias normalization and canonical
strict validation for the whole batch before mutations. Preserve observed aliases,
session inheritance, nullable optional producer fields and unknown-runtime generic
fallback. Reject unknown event operations, extras, conflicting aliases and wrong
container/item/scalar types. No truthy fallback that repairs malformed data.
Unknown-event silent ignore is intentionally tightened to typed 422. Preserve 413
for existing batch/body caps, and P-015 forbidden trust assertions and P-014 quotas.

Use shared bounded strict types matching config LIMITS and engine identity grammar.
Reject C0/DEL in IDs, URI, title and artifact strings without rewriting identity.
Prose text/summary/reason may contain LF/tab; reject other C0/DEL, including NUL.
Validate hashes, enums and required session/node IDs before writes. Keep engine
validation as defense in depth; standalone core valid-call contracts remain intact.

REST validation errors use fixed invalid_argument text and bounded safe field/code
locations, never input/ctx/raw unknown names. Unexpected errors return internal and a
server-generated correlation UUID, never exception text. Ignore arbitrary incoming
correlation values as diagnostic identifiers. Known typed errors retain safe static
messages and reviewed bounded details, with credential redaction.

Log exception class, generated correlation ID and sanitized stack-frame metadata;
do not log str(exc), raw params/body/headers or raw exc_info. This supplies server-side
diagnostic detail without leaking credentials embedded in an exception/cause.
The older P-021 spec's raw exc_info plan is superseded by this measured leakage concern.

Guard the complete MCP call including auth/schema resolution and SDK argument
validation; direct call, stdio and HTTP must get safe typed result envelopes. SDK
validation can drop extras and echo inputs before the function runs, so _call alone
does not satisfy this boundary. Sanitize malformed JSON-RPC envelope errors before
SDK response/log rendering; protocol status/codes remain protocol errors, not an
invented REST 422. Use installed public extension points/subclass wrappers, no edits
to site-packages or guesses about SDK-private contracts.

Pure ASGI bounded actual-byte admission covers REST and MCP before downstream parsing
or writes, including no-length/chunked/understated length. Reject overflow immediately
without buffering/draining beyond the cap. Configure installed SDK's own
max_request_body_size to the same LIMITS value for standalone parity. Verify actual
TCP chunked requests separately from synthetic ASGI false framing/disconnect cases.

No consultant dissented on these principles. Domain measured NUL errors and other
controls persisting on real 42201, and SDK2.3 limits/validation behavior. Evidence is
not implementation proof. Acceptance includes malformed shape matrices, aliases,
exact unchanged snapshots for bad-tail batches, secret-bearing forced engine/auth/
schema errors, hostile correlation headers, real HTTP/stdio SDK validation, chunked
limits and output/log canaries, independent QA/red-team and full checks/dogfood.
