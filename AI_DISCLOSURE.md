# AI-use disclosure

**Project:** Pedigree — git blame and git revert for what an AI agent believes.
**Event:** WeMakeDevs × FalkorDB "Graph Hacks: Context for AI Agents" (Oct 15–18 2026).
**Participant:** Vedant Mahajan (solo).

## Tools used

I built Pedigree with AI coding assistants: **OpenCode** (run through **T3 Code**) using
**DeepSeek V4.1 Flash Free** (`opencode/deepseek-v4.1-flash-free`), organised as a
multi-agent workflow (orchestrator, builder, QA verification, security red-team,
domain researcher, architect, eval statistician, technical writer). AI assistants wrote
most of the code, tests and first drafts of documentation under specifications and
acceptance tests that were derived from a written design pack.

The F-09/F-10/F-11 continuation used **Codex through T3 Code**, running **gpt-6.1-sol**,
with separate builder, QA and review subagents. It implemented and verified the gate,
REST/MCP contracts, Claude hook adapter, graph workspace and synthetic demo seeder.
Adapter verification used synthetic
payloads and localhost transport tests; installed Claude Code execution was not verified.

The F-12..F-16 continuation (Oct 16) used **Codex through T3 Code** with **gpt-6.1-sol**
again, plus role-specialist subagents (architect, red-team, domain researcher, QA). It
implemented the capture-trust consult and ADR-008, the F-13/15 isolation and concurrency
suites, the E1/E2 evaluation harness, the deployment container, and the README /
WALKTHROUGH / blog / submission documents. Two architect subagents failed on provider rate
limits and their analysis was completed by the orchestrator in a documented role-switch
(`docs/consults/007-capture-trust/architect.md` states this on its first line); a provider
quota also blocked installed-runtime capture, which is recorded in
`docs/consults/opencode-spike.md` instead of being papered over.

The subsequent Oct 16 hardening used **Codex through T3 Code**, **gpt-6.1-sol**,
with independent QA and statistical-review subagents. It repaired what-if cleanup and
snapshot comparison, isolated-source audit coverage, destructive test-fixture cleanup,
and clustered evaluation publication. One bounded free OpenCode session completed a
synthetic read and captured genuine before/after hook payloads; the final model response
timed out. This is payload-contract evidence, not a completed Pedigree OpenCode adapter
or real-session coverage/friction evaluation.

## What the human did (not the AI)

- Chose the project, its scope and the time-boxed plan (the design pack this repository
  was built from; the plan documents are committed under `docs/`).
- **Pending human confirmation:** verify the environment and review checkpoint evidence
  in `docs/05-PHASES.md` and `docs/00-HUMAN-CHECKLIST.md`. Agent-run checks are not human review.
- **Pending:** run/review the walkthrough once written, and explain the graph model,
  Cypher queries and revocation protocol before submission.

*(This section is completed by the human before submission — see `docs/00-HUMAN-CHECKLIST.md` step 9/13.)*

## Honesty rules this repository follows

- Every benchmark number in the README and the blog post comes from committed scripts
  (`make eval` → `evals/results/*.csv` → `scripts/extract_numbers.py` → `docs/NUMBERS.md`)
  and is enforced by `scripts/check_numbers.py`. No script, no number.
- Third-party projects are described only from sources read and dated in `docs/research/`.
- Baselines B0–B5 in `evals/baselines.py` are documented **emulations** of published
  semantics, not the vendors' products.
- Unflattering results are reported as they are (see `docs/03-EVAL-AND-DEMO.md` §7).
