# Domain consult

**Answer.** Choose **A**, labelled “observed read capture; gate contract tested; other capture incomplete.” Implement a dependency-free plugin with injectable transport and hooks. Send `/v1/events` batches containing session, source and session_read; use `/v1/gate`’s nested `action` and `session_id`, without tenant/operator credentials. Do not copy the Claude adapter’s raw command summary or post-read filesystem hashing.

Hash a versioned canonical descriptor of the observed read view: canonical project-relative path, display text, range, totalLines and truncation. Give it a distinct read-view URI/source kind; this identifies returned content, **not filesystem bytes**. Never use that digest for `path@file_sha256` artifact lookup. Missing/malformed display, directory reads and inconsistent paths become explicit capture gaps. Resolve real paths and reject symlinks escaping the project; disclose relative paths only. Transmit hashes and bounded metadata, never bodies, output wrappers, preview, commands or error details.

Await capture acknowledgements before subsequent gates; serialize per session. Deduplicate by session/call, preserve distinct read versions, and retain a local session gap latch across restart. Unsupported tools, failed capture, partial ingestion, missing session and window eviction must not become an apparently clean high-risk gate. Block unsupported actions conservatively; require re-verification when lineage is incomplete. Server windows are bounded approximations, not complete histories.

Throw sanitized errors for both block and reverify; reverify means the operation did not execute and needs out-of-band review. Do not claim a native ask/approval flow. On gate outage or malformed response, deny side-effecting tools. Do not catch these deliberate throws in a fail-open transport handler.

**Evidence / confidence.** **V:** genuine fixture `opencode-recheck-2026-10-16-shape.json:17-55` supplies before args and after display; schemas `:115-136`, events route and ingest `:415-428` establish batch/session contracts. Node 24.13.1 executed an erasable-TypeScript `node:test`/assert probe: 1 passed, including erased package type import, no downloads. **D:** official [plugins](https://docs.opencode.ai/docs/plugins/) show throw-to-prevent-read; [Node TypeScript](https://nodejs.org/download/release/v24.13.1/docs/api/typescript.html) supports type stripping without type checking. Use `node --test` with explicit test paths, replay fixture, injected HTTP failures and execution spies; assert rejected hooks never invoke tools. **U:** installed throw/retry behavior, writes and coverage remain unmeasured.

**Risks.** Other plugins, bypassed hooks, process crashes and unobserved reads can evade capture; hashes do not establish trust.

**What changes my mind.** Installed denial/reverify evidence and genuine write/action fixtures, plus measured capture omissions, justify expanding support.
