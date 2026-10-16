# Answer

Choose A, labelled observed-read capture with conservative gating; F-08 remains incomplete. Unknown tools must never inherit low risk merely because their command was omitted for privacy.

Minimal contract:
- Build allowlisted JSON only: runtime-owned session/call identity, opaque workspace-relative source locator, digest and read edge. No raw output, preview, title, file body, command, environment, URL credentials or exception text. Fixed operator-configured endpoint; HTTPS except loopback; reject redirects; bounded requests/responses. Agent token only; no tenant/operator fields.
- Resolve paths against the configured workspace; reject outside roots, symlink/junction escapes and credential-file exclusions before reading/hash work. A skipped dependency marks capture incomplete. Avoid transmitting absolute paths, which also reveal private information.
- Hash observed display text in a distinct range/representation URI namespace. Never use that digest as raw-file `path@sha256`: newline normalization, partial/truncated reads and filesystem races invalidate that claim. Until byte equivalence is established, omit artifact lookup and report cross-session write linkage unsupported. Hashless path identity cannot distinguish versions.
- Bind session/call/tool to runtime hook inputs, never model arguments. Pair hooks; serialize capture acknowledgements before later gates; mark pending, malformed, failed, unsupported or oversized captures incomplete. Deduplicate retries without creating duplicate actions. Persist incomplete state across restart or treat resumed sessions as incomplete. Reject model-supplied risk/audience/dependencies; explicit dependencies otherwise bypass the window.
- Gate with current GateRequest. Apply local conservative high-risk classification without sending commands. Incomplete/unknown sessions, window eviction, outages, malformed responses and unknown decisions deny high-risk execution. `block` denies; `reverify` also denies until independent approval exists: returning Claude's `ask` JSON is not OpenCode approval. Never automatically retry the action.

# Evidence and confidence

V (source inspection): schemas.py:115-134; routes/events.py:38-64 (sequential writes, untrusted sources); adapters.py:75-91 (unknown events disappear); engine/gate.py:46-56,93-97,202-216 (default low, dependency substitution, empty-lineage allow); engine/ingest.py:168-191 (version identity). Claude hook:44-63,127-130 hashes current bytes, forwards Bash commands, fails open; do not copy these behaviors.

V (fixture): opencode-recheck-2026-10-16-shape.json:17-53 establishes one read and display range only. D: before-hook throwing blocks per IDEA §8.2. U: installed reverify/error/timeout enforcement.

# Risks / what changes my mind

Agent-writable plugin/credentials remain bypassable. Require executable adversarial cases: secret-bearing output/commands, junction swaps, partial/changed reads, forged session/low risk, duplicate/out-of-order hooks, partial batch failure, 51-read eviction, restart, HTTP redirect/timeout/invalid verdict. Genuine isolated runtime denial/approval evidence and byte-exact read evidence would justify relaxing these limits.
