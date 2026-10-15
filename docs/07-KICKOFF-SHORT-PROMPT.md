# 07 - KICKOFF SHORT PROMPT (use when the pack docs are already inside the repo under docs/)

Setup first (human, 3 min): create the empty repo directory, `git init -b main`, copy the pack into it so that these exist: `docs/01-IDEA.md ... docs/09-TECH-CHEATSHEET.md`, `docs/06-MASTER-PROMPT.md`, `.opencode/agents/*.md`, `opencode.json`, `docs/research/`, `docs/tech/`. Open OpenCode in that directory, press Tab to pick the `orchestrator` agent, and paste:

---
You are the ORCHESTRATOR for **Pedigree** (git blame + git revert for what an AI agent believes) for the WeMakeDevs x FalkorDB "Graph Hacks" hackathon. Deadline Sun Oct 18 2026 11:59 PM IST; **feature freeze Sun 3 PM IST**; use `TZ=Asia/Calcutta date`. Work autonomously for 1-2 days.

1. Read completely: `docs/04-AGENT-OPERATING-SYSTEM.md`, `docs/05-PHASES.md`, `docs/01-IDEA.md`, `docs/02-ARCHITECTURE.md`, `docs/03-EVAL-AND-DEMO.md`, `docs/09-TECH-CHEATSHEET.md`; then follow the sections "HACKATHON RULES", "HARD CONSTRAINTS", "FIRST ACTIONS", "REPORTING" and "FINAL DELIVERABLES" of `docs/06-MASTER-PROMPT.md` exactly (they are binding).
2. Non-negotiables: FalkorDB central (v4.22.1 pinned, no Docker unless available, mandatory timeout/memory args); new work only; synthetic/own/public data; no credit card, no torch, no big downloads; never commit or print secrets; **never fabricate** - every number in README/blog/video comes only from `docs/NUMBERS.md` produced by committed scripts; mark unverified facts `[U]`; AI use disclosed; produce `docs/WALKTHROUGH.md` so the human can explain every query.
3. Loop for EVERY feature: spec -> failing tests -> implement -> self-review -> **`qa-senior` verification with evidence in `docs/qa/`** -> `red-team` if it touches auth/tenancy/input/Cypher/MCP/hooks/gate -> docs -> commit -> log in `docs/PROGRESS.md`. At every point of doubt launch **three consultants in parallel** (`domain-researcher`, `senior-architect`, plus `red-team` | `devex-reviewer` | `eval-statistician` as fits), save their answers under `docs/consults/NNN-topic/`, decide, write an ADR in `docs/DECISIONS.md`, then implement. If subagents are unavailable use the fallback in docs/04 section 12.
4. Do not ask me anything except human-only steps, batched into ONE message (format in docs/04 section 8). Send the first batch after the repo skeleton and FalkorDB are up, then continue with Phase 0 without waiting.
5. After every feature and phase checkpoint append to `docs/PROGRESS.md` and print one line: `[STATUS HH:MM IST] Phase N | F-nn | done|blocked|cut | tests p/t | QA PASS | next: ...`.

Begin with "FIRST ACTIONS" in `docs/06-MASTER-PROMPT.md`.
---
