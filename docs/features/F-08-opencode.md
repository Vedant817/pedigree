# F-08 OpenCode adapter: observed read-only slice

Full feature remains implementing. Consult 008/ADR-009 chooses an opt-in read-only
slice from a genuine installed OpenCode 1.19.0 payload. Native write probing was
provider-blocked; write/edit/shell/MCP mappings and real coverage are unverified.

Implemented contract to verify:
- Disabled without PEDIGREE_OPENCODE_ENABLED=1; disabled hooks send no data.
- Enabled native reads: validate paths/credential exclusions, pair runtime-owned
  session/call IDs, call nested /v1/gate, deny block/reverify/unknown/unavailable.
- After successful observed display output, send session/source/session_read to
  /v1/events. Source is an untrusted observed read view, not whole-file bytes.
- Stable project/range URI plus observed descriptor digest distinguishes versions;
  no artifact lookup, no cross-session write claim, no raw content/output/command,
  absolute path or operator credential forwarded.
- Unsupported tools always denied before execution. Failed/ambiguous capture makes
  the session incomplete. Bound transport, memory, body and response sizes; no
  redirects or remote plaintext HTTP. No automatic batch retries.

No schema/query changes. Existing REST capture authority and canonical Source
identity apply. Scope excludes installed approval UX, durable spool/replay (F-22),
write/action capture, canary recall, coverage and benign friction.

Acceptance evidence: builtin Node regression suite with genuine-fixture mapping,
privacy canaries, ranges/version identity, path containment/symlinks, duplicate and
out-of-order hooks, failure/status/redirect/response bounds, disabled configuration,
gate denials and unsupported-tool execution spies. A Python integration test starts
a real local API, invokes the Node plugin hooks using the genuine fixture and proves
persisted Source/session window/tenant isolation in FalkorDB 42201. Label that hook
replay, not installed OpenCode execution. QA and red-team independently rerun.
