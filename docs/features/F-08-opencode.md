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

## Implementation status (2026-10-16)

Implemented in `adapters/opencode/` (`pedigree.js` entry, `pedigree-core.js` core,
`README.md` install/config/limits; dependency-free ESM, no npm packages):

- Builtin Node suite, 38 tests: `fixture-mapping.test.js` (exact allowlisted wire
  contract from the genuine 1.19.0 payload), `hooks.test.js` (gate/denial/ordering/
  latch matrix), `paths.test.js` (traversal, symlink/junction escape, credential
  exclusions, display validation, win32 stream/drive-relative denial, case
  canonicalization, dot-dot literal names vs `..`-segment escapes), `privacy.test.js`
  (canaries + body-key allowlist), `bounds-config.test.js` (opt-in, fail-closed
  misconfiguration, clamps, memory/URI bounds). Run under pytest by
  `tests/unit/test_opencode_adapter_suite.py`.
- End-to-end hook replay: `tests/integration/test_opencode_plugin.py` drives the
  genuine fixture through a Node subprocess into a live API + real FalkorDB 42201,
  asserting the persisted Source identity with an independently recomputed digest,
  forced `untrusted` integrity, Session runtime + read window, revoke → `reverify`
  denial with no capture, per-tenant isolation, and (Windows) case-variant
  convergence on one Source. Driver: `tests/driver.js`.
- Install contract updated from the current runtime docs + genuine recheck: project
  plugins load from `.opencode/plugins/`; the entry exports one named plugin function.

## Independent review (2026-10-16) and follow-up fixes

`docs/qa/F-08.md` (FAIL: the tracked privacy canary matched the repository secret
scanner; plus stale-doc and claim-wording findings) and the red-team evidence in
`docs/qa/redteam-F-08.md` / `scratch/redteam-f08/` resulted in:

- Windows alternate data streams (`id_rsa::$DATA`, `file:stream`) and drive-relative
  forms (`C:file`) are now denied at the path stage (`path_stream`) before any
  transport; on-disk case is canonicalized with the native resolver so
  `CASE.TXT`/`case.txt` mint one Source identity.
- The canary literal no longer exists in git history (commit amended before push);
  regression tests: `tests/security/test_security_F08.py` (stream/drive-relative
  denial with a silent listener proving zero connections; strict-xfail watchdog for
  read-window eviction), win32 tests in `paths.test.js`, case test above.
- Disclosed (not fixed, not overclaimed) in `adapters/opencode/README.md` known
  limits: bounded latch memory (evicted-session ring), the server's bounded
  `pedigree_read_window` (default last 50 reads) influencing revocation, and TOCTOU
  between validation and the runtime read. P-014 (`/v1/events` bypassing node_cap)
  is pre-existing and out of this slice's scope (`AUDIT.md`).

Builder fix-verification evidence is in the QA addendum (`docs/qa/F-08.md`): independent
round 1 found a secret-scan canary and stale docs; independent round 2 found that the
review-evidence commit itself had reintroduced the canary literal (plus one fail-closed
path over-denial) — both closed by redaction + the segment-aware escape fix and the
commit amended in place (`bb9511a`, unpushed); round 3 re-confirmed PASS with fresh runs
of every gate and of the reviewer's own probe harness. F-08 stays implementing;
installed-runtime acceptance of this plugin file remains unverified.
