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

## What the human did (not the AI)

- Chose the project, its scope and the time-boxed plan (the design pack this repository
  was built from; the plan documents are committed under `docs/`).
- Verified the environment (FalkorDB running, tests green) at the checkpoints described
  in `docs/05-PHASES.md` and the human checklist `docs/00-HUMAN-CHECKLIST.md`.
- Runs and reviews the walkthrough in `docs/WALKTHROUGH.md`, can explain the graph model,
  every Cypher query and the revocation protocol.

*(This section is completed by the human before submission — see `docs/00-HUMAN-CHECKLIST.md` step 9/13.)*

## Honesty rules this repository follows

- Every benchmark number in the README and the blog post comes from committed scripts
  (`make eval` → `evals/results/*.csv` → `scripts/extract_numbers.py` → `docs/NUMBERS.md`)
  and is enforced by `scripts/check_numbers.py`. No script, no number.
- Third-party projects are described only from sources read and dated in `docs/research/`.
- Baselines B0–B5 in `evals/baselines.py` are documented **emulations** of published
  semantics, not the vendors' products.
- Unflattering results are reported as they are (see `docs/03-EVAL-AND-DEMO.md` §7).
