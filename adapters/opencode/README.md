# Pedigree OpenCode adapter

Explicitly enabled capture/gating adapter for [OpenCode](https://opencode.ai/).
While enabled it gates and captures the observed native `read`, `write`, `edit`
and `bash` forms. Reads are *observed read views*; writes/edits are verified file
artifact actions; successful Bash output is an untrusted hash-only source.
Unsupported tools and ambiguous forms are denied. Scope, limits and exclusions:
[`docs/features/F-08-opencode.md`](../../docs/features/F-08-opencode.md) and
ADR-009 in [`docs/DECISIONS.md`](../../docs/DECISIONS.md).

**Evidence boundary.** Native read/write/edit/Bash success shapes and failed
Bash/edit behavior were observed in installed OpenCode 1.19.3 using beam-free.
The structural evidence contains no content or credentials:
`docs/consults/opencode-1.19.3-tool-shapes.json`. Node tests and live API/FalkorDB
hook replay verify mapping, provenance, privacy and failures. Installed plugin
acceptance and its exact limits are recorded separately in
`docs/qa/opencode-native-local.md`; replay is never counted as installed proof.

## Install

1. Copy both files side by side into `.opencode/pedigree/`:
   `pedigree.js` and `pedigree-core.js` (the entry imports `./pedigree-core.js`).
   Register only the entry file's absolute path in the project's `opencode.json`
   `plugin` array. This explicit entry registration was used in installed acceptance.
   Keep the core outside the automatically scanned `.opencode/plugins/` directory:
   it exports helpers, not plugin entry functions.
2. No build step and no npm dependencies: plain Node ESM using builtins only
   (`node:crypto`, `node:fs`, `node:path`). Do not rename one file without the
   other.
3. Export contract: one named plugin function, `PedigreePlugin`. Do not add a
   second exported function (the runtime may invoke every exported function,
   which would register duplicate hooks).

## Configuration (environment)

| Variable | Default | Meaning |
| --- | --- | --- |
| `PEDIGREE_OPENCODE_ENABLED` | unset | Must be exactly `1` to enable. Anything else disables the plugin (no hooks, no network). |
| `PEDIGREE_OPENCODE_TOKEN` | required | Agent tenant bearer (`ped_a_…`), or a legacy tenant token with agent privileges. An operator bearer (`ped_o_…`) makes the configuration invalid and denies tools before networking. Never supply the deployment admin secret. |
| `PEDIGREE_OPENCODE_URL` | `http://127.0.0.1:8000` | Pedigree API base. HTTPS anywhere; plaintext HTTP only on loopback. No credentials in the URL, no query or fragment. |
| `PEDIGREE_OPENCODE_TIMEOUT_MS` | `3000` | Per-request timeout, clamped to `100`..`30000`. |
| `PEDIGREE_OPENCODE_MAX_RESPONSE_BYTES` | `1048576` | Response-size cap, clamped to `4096`..`8388608`. Responses that exceed it (even with an untrue `content-length`) are treated as a failed request. |

## Behaviour while enabled

For every native `read` call the plugin:

1. Denies tools outside observed `read`, `write`, `edit`, `bash` forms. MCP,
   delegation, patch and other native tools remain denied.
2. Validates the path: inside the canonical project root, not a `..`/symlink
   escape, not a credential file (`.env*`, keys, `.ssh`, `.aws`, …). On Windows,
   drive-relative (`C:file`) and alternate-stream (`file:stream`, `id_rsa::$DATA`)
   forms are denied outright, and existing paths are canonicalized with the
   native resolver so `CASE.TXT` and `case.txt` yield one identity.
3. Ensures the session, then calls `POST /v1/gate` with
   `{action:{tool:"read", summary:"read <relative path>", effect:"reversible",
   risk:"low"}, session_id, record:false}`. `allow`/`warn` proceed; `block`,
   `reverify`, unknown decisions, malformed bodies and outages deny.
4. After the read completes, validates the observed display view and captures
   `POST /v1/events` with `session`, `source_read` (the read-view URI + digest)
   and `session_read` in one batch.

Captured identity is a project-relative, versioned read view — **not** file
bytes:

- URI: `readview:v1/<project-key>/<relative path>#L<start>-L<end>`
- Digest: SHA-256 over the canonical JSON descriptor
  `{"v":1,"path":…,"line_start":…,"line_end":…,"total_lines":…,"truncated":…,"text":…}`
  of the *displayed* text/range/truncation only.

Never transmitted: file bodies, the tool's output wrapper, previews, titles,
commands or args beyond the relative path, absolute paths, the operator token,
exception details. Source nodes are forced `untrusted` by the server for agent
tokens; the adapter never asserts trust, tenant or dependencies.

Failure semantics:

- A denied read never executes (the before hook throws; a denied tool produces
  no after hook in the runtime).
- A completed read whose capture fails is **completed-but-uncaptured**: the
  after hook logs one line (`pedigree: capture incomplete (…)`) and latches the
  session. Every further operation in that session is denied until the session
  is restarted.
- Ambiguous hook pairs (duplicate call IDs, unpaired after hooks, malformed
  payloads, evicted session state) latch the session too; gate outages deny the
  read but do not latch it.

Hard limits: pending calls per session `64`; remembered acknowledgements `512`;
tracked sessions `64` (LRU) with an eviction ring of `256`; display text
`4 MiB`; path length `1024`; view URI `512` (server contract); gate summary
`300` (server contract). Requests are single-attempt (no automatic retry), no
redirects are followed, and every request is bounded by the timeout above.

Known limits (must not be over-read):

- Failed native edit was observed to omit the after hook. An unresolved mutation
  denies later tools; malformed after metadata also latches the session.
- Latch memory is bounded: after more than 64 tracked sessions churned, a
  session evicted from the tracking map is remembered as incomplete only within
  a 256-entry ring; beyond that, an old session ID that reappears after heavy
  churn can be treated as new. Bounded memory over unbounded forgetting
  (Red-team F-08, disclosure).
- The gate consults a bounded influence window (`pedigree_read_window`, default
  the last 50 distinct reads per session). A revoked source evicted from that
  window by 50 newer reads is no longer consulted server-side (the red-team
  probe observed one read allowed after eviction); re-reads of a revoked view
  are denied only while that view is inside the window. Server semantics,
  disclosed; `tests/security/test_security_F08.py` carries a strict xfail
  watchdog that flips if eviction semantics change.
- TOCTOU: paths are validated in the before hook and again in the after hook,
  but a symlink swapped between those points is outside the threat model. The
  digest covers only the *observed display view* (what the runtime reported),
  never asserted as identical to the bytes on disk.
- Durable replay/ack state across plugin restarts is out of scope (F-22).
  Restarting loses dedup/latch state for that session, while unsupported tools
  remain unconditionally denied.
- Session IDs are namespaced per canonical project (`oc_<project-key>_<sid>`);
  the same runtime session string in another project is a different session,
  and another tenant is always a separate graph.

## Tests

Builtin Node (no dependencies), from the repository root:

```bash
node --test adapters/opencode/tests/fixture-mapping.test.js adapters/opencode/tests/hooks.test.js \
  adapters/opencode/tests/paths.test.js adapters/opencode/tests/privacy.test.js \
  adapters/opencode/tests/bounds-config.test.js adapters/opencode/tests/native-tools.test.js
```

- `tests/unit/test_opencode_adapter_suite.py` runs the same suite
  under pytest.
- `tests/integration/test_opencode_plugin.py` starts a real local API and
  FalkorDB, then drives the genuine fixture through `tests/driver.js` with a
  Node subprocess: persisted read view + independently recomputed digest,
  untrusted integrity, session read window, revoke-then-deny, tenant isolation,
  and (on Windows) `CASE.TXT`/`case.txt` convergence on one Source. This is a
  **hook replay**, not installed OpenCode execution.
- `tests/security/test_security_F08.py` holds the red-team regressions: Windows
  stream and drive-relative paths denied with zero network connections (silent
  listener) and a strict-xfail read-window eviction watchdog.
- `tests/driver.js` is a manual replay harness: a job JSON
  `{"project": "<dir>", "hooks": [{"phase": "before"|"after", "input": …, "output": …}]}`
  prints one JSON result per hook and exits `0` even for per-hook denials.

## Troubleshooting

- Nothing is captured: check `PEDIGREE_OPENCODE_ENABLED=1` and
  `PEDIGREE_OPENCODE_TOKEN` are visible to the OpenCode process, and that the
  API base is reachable. A misconfigured adapter denies everything (fail-closed)
  with `pedigree: adapter configuration is invalid…`.
- `pedigree: session capture is incomplete` on stderr: the session hit a
  capture gap (see failure semantics). Restart the OpenCode session; inspect the
  Pedigree API logs/events for the session.
- `tool "…" is not supported`: that tool is outside the observed native allowlist.

## Native write, edit and Bash

Write accepts only observed `filePath`/`content`; edit accepts only observed
`filePath`/`oldString`/`newString`, with one exact old-string occurrence. Bash
accepts only observed `command`. Unobserved options such as replace-all and
alternate working-directory forms are denied rather than guessed.

File mutations validate the nearest existing parent before creating files, and
revalidate after execution, excluding credentials and escaping symlinks/junctions.
Relative paths resolve against the runtime directory while identities and
confinement remain scoped to the canonical worktree root. Windows normalized
trailing-dot/space aliases and device names are denied before execution.
Before the gate, write hashes intended UTF-8 content; edit safely reconstructs
the intended single replacement and hashes it. After execution the actual bounded
file hash and observed result path must match. The action stores a relative
`file:v1/<project>/<path>` artifact and `artifact@sha256` version key. No Memory
text is invented. Session read-window dependencies provide the action's lineage.

All mutations use unknown effect/high risk. Bash summaries contain only the command
digest, so the server cannot inspect/classify command text. High-risk operations
following untrusted input may require re-verification even for benign commands.
A Bash result needs matching arguments, matching reported output, exit zero and
untruncated bounded output. Its action is recorded before its hash-only output
Source enters the read window. Nonzero or missing exit never produces successful
action evidence; it latches the session because no failed-attempt API exists.

Commands, output, diagnostics, diffs and file bodies remain local. File/output
bytes are bounded by the same display limit. Failed delivery latches the session;
there are no automatic retries. Durable restart/ack state, arbitrary Bash file
provenance, cross-session artifact links and unobserved tools remain unverified.
Bash is not a filesystem sandbox; file-tool path confinement does not constrain
paths an arbitrary shell command may access.

The historical F-08 feature spec and ADR-009 describe the earlier read-only slice.
The proposed extension and its review boundaries are in
[`docs/adr/F-08-native-capture.md`](../../docs/adr/F-08-native-capture.md).
