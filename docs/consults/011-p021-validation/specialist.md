# Security specialist: validate before normalization, contain SDK failures

Choose A, with strict raw-field checks before normalization and strict canonical
models afterwards. Validate the complete batch before any write. Reject unknown
operations/extras and conflicting alias values; preserve only documented aliases.
Do not let `or []`, `or ""`, `.lower()` or `dict(raw)` repair wrong types. Require
actual arrays of bounded strings, strict booleans/integers, bounded event counts,
field lengths and existing identifier rules. Reject NUL and URI controls without
trimming or rewriting identities; allow intentional multiline memory text under
an explicit control-character policy. Validate even fields later unused/dropped.

Evidence: `adapters.py:normalize_event` silently drops unknown operations, defaults
unknown source kinds, and uses truthy fallbacks; `schemas.py:EventsPayload` accepts
arbitrary event dictionaries. `app.py:BodySizeMiddleware` checks only declared
length, and generic handlers expose exception text. `_resolve` calls precede
MCP `_call`, leaving authentication/registry/schema failures outside containment.

Installed SDK evidence matters: `mcpserver/tools/base.py:153–157` interpolates a
Pydantic ValidationError into ToolError; `server.py:445–456` returns its text and
logs unexpected causes via `logger.exception`. `streamable_http.py:588–595` also
echoes invalid JSON-RPC envelope values. SDK argument parsing is therefore not a
safe replacement for shared validation. Guard actual transport dispatch, tool
arguments and auth resolution; preserve protocol errors but sanitize their text.
Exercise stdio and real HTTP dispatch, not only direct function calls.

Use pure ASGI actual-byte admission before downstream parsing/writes, capped at
256 KiB including chunked/no-length/understated-length bodies and the MCP mount.
Reject excess before invoking the endpoint; do not emit a second response after
response-start. The installed `streamable_http_app` accepts
`max_request_body_size`; set it explicitly too. Test exact-limit boundaries,
multi-chunk overflow, malformed/duplicate length and disconnects. Live h11 framing
rejections and synthetic ASGI understated-length tests are distinct evidence.

Return static validation/internal messages plus server-generated correlation IDs.
Never echo rejected inputs, exception text, arbitrary correlation headers or raw
tracebacks. Log only correlation ID, fixed operation, exception class and sanitized
stack frame metadata; `exc_info=True` can expose secrets embedded in causes.
Known typed errors also need bounded, reviewed details.

Adversarial matrix: scalar/list/null/bool substitutions; alias conflicts and
unknown extras; controls; oversized list/items/body; valid-prefix/invalid-tail
batch with unchanged graph; malformed SDK arguments/envelopes; forced secret-bearing
faults in engine, registry resolve and schema setup; hostile correlation headers.
Assert no secret/input canaries in every response and captured log, and no writes
on malformed batches. Confidence: high from source; no new attacks executed here.
