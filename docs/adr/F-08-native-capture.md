# Draft: observed native OpenCode capture

Status: implementation proposal under Consult015; independent review pending.
This extends the read-only boundary of ADR-009 without changing the public API,
MCP contracts, database schema or server gate policy.

Installed OpenCode 1.19.3 exposes matched native read/write/edit/bash hooks.
Implement only these observed argument forms. Unsupported options and tools deny.
The structural fixture is `docs/consults/opencode-1.19.3-tool-shapes.json`.

Keep read-view descriptors and session lineage semantics. Resolve relative tool
paths against the runtime directory, retain canonical worktree namespaces, and
deny an external runtime directory. Before and after file mutations, validate
requested and reported paths, nearest existing parents, symlink confinement and
credential exclusions. Reject Windows normalized aliases/device paths. These
checks detect some races; they do not sandbox the runtime filesystem writer.

Gate mutations as unknown/high. Digest-only Bash cannot be classified from its
hidden command. Do not adopt the initial reversible/low proposal rejected by the
domain/security reviews. Existing policy may require re-verification after any
untrusted read; the plugin has no approval bypass.

Hash intended UTF-8 writes before execution and compare bounded post-file bytes.
For edits, accept only one exact old-string occurrence in bounded valid UTF-8,
reconstruct the full expected replacement and compare its post-file digest.
Store hash-only Action artifact/version identity through `action_executed`.
Matching digests establish observed equality, not exclusive filesystem authorship.
Do not invent Memory nodes or claim cross-session file lineage.

Bash needs matching arguments/output, explicit integer exit zero and untruncated
bounded output. Record the action with the existing session dependencies before
adding the untrusted output digest to its read window. No command, output, body,
diagnostic or diff goes to Pedigree. Nonzero/missing exit has no truthful failed
attempt contract: emit no success action and latch. Missing mutation after-hooks,
mismatches and delivery failures deny later tools. Duplicate acknowledged after
callbacks do not resend events; retries lack durable receipt semantics.

Alternatives rejected: guessed runtime shapes, blanket low-risk mutations,
poststate-only exact authorship claims, shell parsing to lower risk, automatic
retries and silent success after a capture gap.

Evidence: Consult015 decision and responses; native Node failure/privacy cases;
real API/FalkorDB integration; `docs/qa/opencode-native-local.md` distinguishes
installed execution from replay. Durable restart state, bounded latch/read-window
eviction, arbitrary shell provenance and independent QA remain separate boundaries.
