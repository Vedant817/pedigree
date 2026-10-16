# Answer

Choose **A**: observed read capture plus conservative before-tool enforcement; F-08 remains incomplete for writes, edits, shell and coverage. Use a dependency-free JavaScript module exporting pure mappers and injected transport, plus the thin plugin hooks.

Serialize hooks per session; await prior captures before gating. Namespace session IDs by project/runtime; deduplicate `(sessionID,callID,phase)` with a durable, content-free acknowledgement ledger. Ensure session before capture/gate. Never replay acknowledged reads: READ timestamps affect the window. A timeout after submission is ambiguous, not acknowledgement; batch ingestion is sequential, not atomic.

Actual REST: bearer token only; `POST /v1/events` with `{runtime:"opencode",session_id,events:[{type:"session"},{type:"source_read",source_kind:"file",id,uri,content_hash},{type:"session_read",node_id:id}]}`. In-batch aliases resolve canonical source IDs. Existing verified whole-file artifact keys may use `GET /v1/artifacts/lookup?key=...`, then session_read. Gate: `POST /v1/gate` with `{session_id,action:{tool,summary,effect,risk,audience},record:false}`; no runtime/args/tenant. Read `decision`, not Claude-specific hook JSON. Throw on block/reverify; reverify requires independent operator remediation and a fresh gate, never an agent trust upgrade.

Hash only observed `metadata.display.text`, with a versioned encoding and range-specific URI including canonical project-relative path and line bounds; this identifies observed text, **not filesystem bytes**. Never use that digest as `path@sha256` for whole-file lookup. Validate range/truncation; unsupported/ambiguous metadata becomes a capture gap. Resolve paths against canonical project root; reject escaping symlinks/outside files. Send neither bodies, outputs nor commands; classify commands locally, sending conservative high/unknown risk when classification is uncertain.

Persist session gaps for unsupported tools, dropped/failed/ambiguous capture, overflow or restart uncertainty; bounded retries cannot clear unreconstructable gaps. Any gap, unavailable/malformed gate, or no-lineage/window-eviction uncertainty prevents automatic high-risk execution. Unknown tools default high/unknown; do not inherit the server's low-risk fallback.

# Evidence / confidence

**V:** genuine fixture lines 17–55 establishes read fields only. `schemas.py:115–135`, `routes/events.py:29–65`, `adapters.py:31–76` establish REST mapping; `ingest.py:168–182,415–429` establishes identity/window; `gate.py:202–203` permits empty lineage. **D:** proposed controls. **U:** installed enforcement beyond observed read.

# Risks / what changes my mind

Node `--test`, builtin HTTP/crypto/fs: fixture mapping, changed-file/range identity, symlinks, concurrency, duplicate/partial-batch retries, outage/reverify, privacy canaries. Existing real-DB API tests prove persistence separately. Genuine bounded write/action and failure-hook evidence could justify B; neither mocks nor read proof establishes installed coverage.
