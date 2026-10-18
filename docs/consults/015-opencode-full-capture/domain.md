# Domain review

Observed write/edit/bash shapes support a bounded slice. Match before/after by session, tool and call ID; use the validated before path, not output display text. Verify success metadata (`exit` exactly zero for bash), and latch malformed, unmatched or failed capture.

**Contract mismatch:** normalization accepts `memory`, `memory_created`, `remember`, not `memory_write`; MemoryEvent lacks content_hash (`src/pedigree/validation.py:122-132,156-164`). Either add a compatible hash-only contract with real-DB tests, or record an Action with artifact_key plus hash-only Source/read link. Existing Action accepts artifact_key, artifacts and relied_on (`validation.py:135-148`); sources merge URI/hash with in-batch aliases (`api/routes/events.py:51-85`). Session lineage uses read_window and record_action (`engine/ingest.py:341-377`).

**Dissent:** blanket reversible/low classification for project writes exceeds verified behavior. Overwriting workflows/config/rules can cause external effects. Use existing policy classification; digest-only bash remains unknown/high because its semantics cannot be recovered. Resolve new-file existing parents and reject symlink escape, drive-relative/ADS/device forms and traversal. Recheck after success: symlinks can change.

Acceptance: installed native write/edit/bash matched hooks; actual file/hash persistence and server lineage; failed exit produces no success evidence; unsupported shapes deny; new-file symlink-parent escape, post-write path race, missing parent, oversized file, duplicate after hook and response loss. Never transmit content, diff, diagnostics, raw command or output. Digest evidence proves observed bytes, not authorization or complete shell influence.
