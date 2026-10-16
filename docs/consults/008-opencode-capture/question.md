# Consult 008: implement OpenCode capture from the observed contract

Context: F-08 is unbuilt. A genuine OpenCode 1.19.0 free-model session captured one
read's before/after hooks. The core REST capture/gate, stable source identity and
operator-bound trust already work. We must now build the adapter without claiming
unobserved tools, losing provenance silently, or transmitting secrets/raw tool output.

Question: what is the smallest defensible adapter contract and verification plan
for this installed runtime, including capture privacy, source version identity,
session windows, and before-tool gate failures/reverify?

Evidence to read:
- docs/consults/opencode-recheck-2026-10-16.md and its -shape.json (genuine read).
- docs/01-IDEA.md sections 7.3 and 8.2; its plugin sketch predates the implemented API.
- src/pedigree/api/schemas.py, api/routes/{events,gate}.py, adapters.py,
  engine/{ingest,gate}.py; actual API schema wins over the old sketch.
- adapters/claude/pedigree_hook.py and docs/DECISIONS.md ADR-008.

Options: A) implement observed read capture plus gate support, leave unobserved
write/edit/bash mapping explicitly incomplete; B) map documented tool arguments
with synthetic tests, then run one bounded synthetic free session to obtain genuine
read/write/action evidence; C) read-only first without enforcing a gate, keep F-08
implementing until a complete supported slice is measured.

Constraints: no paid model/service, no new heavy dependencies, no secrets printed,
committed or forwarded as tool outputs. Only isolated synthetic runtime work may
be recorded. No operator token in plugin. No tenant argument. Capture must not
claim trusted sources. FalkorDB 42201 remains real for API proof. Node 24.13.1 is
installed; prefer executable contract tests that need no npm package downloads.
Do not run another model session or DB benchmark as part of this consult.

Already verified: genuine read before input={tool,sessionID,callID}, output.args.filePath;
after input adds args, after output={title,output,metadata}; fixture preserves actual
read display text/range. Full suite 391 passed/1 optional ACL skip; source tree clean
at 879a3de. Old plugin sketch's /v1/gate payload is incompatible with GateRequest.

Special focus: avoid hashing changed filesystem bytes while claiming they are the
actual read result; do not send raw outputs/commands/file bodies by default; don't
turn read capture or API tests into installed write/capture-coverage proof. Assess
how unsupported tools, failed captures, symlinks/outside-project files, partial reads,
duplicates and service outages affect later high-risk gate decisions.

Answer <=400 words: Answer | Evidence (local lines or primary docs actually read) |
confidence V/D/U | Risks | What would change my mind. Write only your assigned
domain.md, architect.md or specialist.md. Do not read the other consultants' answers.
