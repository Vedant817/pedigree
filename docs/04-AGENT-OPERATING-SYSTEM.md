# 04 - AGENT OPERATING SYSTEM (how the coding agents work)

Goal: let the coding agent (OpenCode via T3 Code, or Google Antigravity) run autonomously for 1-2 days, with **independent verification of every feature**, consultation at points of doubt, and an evidence trail that makes the final claims honest.

## 1. Roles
| Role | Mode | Writes | Purpose | Invoked when |
|---|---|---|---|---|
| **Orchestrator** | primary | everything | runs phases + loop, owns PROGRESS/DECISIONS, launches others, applies cut order | always (the session you talk to) |
| **Builder** (1..2 parallel on independent features) | subagent | src/, tests/ | test-first implementation of one spec | step 3 of the loop |
| **Senior QA** | subagent | docs/qa/, tests/ | independent verification with evidence; can add failing tests; never edits src | step 5; phase checkpoints; before release |
| **Domain Researcher** | subagent | docs/consults/ | verified answers (docs, papers, 30-second experiments on real FalkorDB) | any doubt about external facts/behaviour |
| **Senior Architect** | subagent | docs/consults/ | design choice, invariants, failure modes, feasibility | any design/schema/protocol doubt |
| **Security Red-Team** | subagent | tests/security/, docs/qa/ | attacks tenant isolation, auth, Cypher, limits, gate, forgery | features touching auth/tenancy/input/Cypher/MCP/hooks/gate; release |
| **Eval Statistician** | subagent | evals/REPORT.md, docs/qa/ | experiment honesty, CIs, sign-off of NUMBERS.md | before running/reporting any benchmark |
| **DevEx/UX Reviewer** | subagent | docs/qa/ | clean-clone test, UI clarity, judge-eyes review | after UI/README milestones; before submission |
| **Technical Writer** | subagent | README, blog, disclosure, demo | verified-facts-only docs | Phase 4 (and drafts earlier) |
Agent definitions: `opencode-agents/*.md` (copy to `.opencode/agents/`). Pattern: **one orchestrator, many stateless specialists**; only the orchestrator launches subagents; subagents return text/files.

## 2. The per-feature loop (every feature, no exceptions)
1. **SPEC** - write `docs/features/F-<nn>-<slug>.md`: behaviour, API/MCP contract, data-model/Cypher touched, invariants, acceptance tests (named), security notes, evidence needed. Ask: *is anything uncertain?* -> consult (section 4).
2. **TESTS FIRST** - builder writes failing tests (unit, integration on real FalkorDB, property where an invariant exists) and shows them failing for the right reason.
3. **IMPLEMENT** - smallest correct change; static parameterised Cypher in `db/queries.py`; no MULTI/EXEC; chunk writes; respect GOTCHAS.
4. **SELF-REVIEW** - builder reviews own diff against the checklist in section 6 and runs `make check` (ruff, mypy if configured, tests, secret scan).
5. **QA VERIFICATION** - senior-qa independently re-runs everything, runs the feature end-to-end, attempts >= 5 adversarial cases, writes `docs/qa/F-<nn>.md` with commands + real output + verdict. FAIL -> back to 3 (max 3 cycles, then consult).
6. **RED-TEAM** (if the feature touches a trust boundary) - `docs/qa/redteam-F-<nn>.md`; every finding gets a failing test then a fix.
7. **DOCS** - update README/API docs/OpenAPI examples and `docs/FEATURES.md` row (feature -> tests -> QA report).
8. **MERGE** - small commit(s) with message `F-<nn>: ...`; tests green on a clean checkout; `git push` is **allowed only at checkpoints** (human can pause pushes; pushes are `ask` in the orchestrator config).
9. **LOG** - append to `docs/PROGRESS.md` (format below); one-line status to the human at milestones.
Parallelism: independent features (e.g. UI and eval harness) may run with two builders on separate branches `feat/F-nn`; the orchestrator merges one at a time and re-runs the suite.

## 3. Definition of done
**Feature DoD:** acceptance tests pass; property/invariant tests where applicable; integration test against real FalkorDB v4.22.1; `make check` green; QA PASS with evidence file; red-team PASS if trust boundary; docs updated; no TODO/FIXME left without an issue entry in `docs/KNOWN_ISSUES.md`; no secrets (script passes); metrics/log fields present for new operations.
**Phase DoD:** the phase acceptance tests in `docs/05-PHASES.md` pass on a clean clone (`scripts/clean_clone_check.sh`); PROGRESS updated; checkpoint tag `phase-N`.
**Release DoD (submission):** all P0 (+ P1 done) features DoD; `make eval` reproduced; `docs/NUMBERS.md` regenerated; eval-statistician SIGN-OFF; devex-reviewer clean-clone PASS; red-team final PASS; README/blog/video numbers match NUMBERS.md (script `scripts/check_numbers.py` greps README/blog for numerals and verifies each appears in NUMBERS.md); AI_DISCLOSURE.md complete; demo recorded; live deploy URL tested (or local fallback documented); human-only checklist done.

## 4. Consult protocol (use at EVERY point of doubt)
**Triggers (any one):** a FalkorDB/Cypher behaviour not in `tech/TECH_REFERENCE.md`/`GOTCHAS.md` or contradicted by a test; algorithm correctness or invariant design; schema/index/constraint change; any security boundary or auth decision; eval design or interpretation; an external fact (rules, API, version, free-tier limit, competitor claim); API/MCP contract change; a flaky test; 2 failed fix attempts; estimate overrun > 1.5x; a feature that might need cutting.
**Procedure:**
1. Create `docs/consults/NNN-<topic>/question.md` using the template below.
2. Launch **three subagents in parallel**, each given only that file path plus the context links: `domain-researcher` (always), `senior-architect` (always), and ONE specialist chosen by requirement:
| Requirement type | Third specialist |
|---|---|
| auth, tenancy, input handling, Cypher, MCP, hooks, gate, secrets | `red-team` |
| README, UI, onboarding, demo story, error messages, naming | `devex-reviewer` |
| benchmark design, metrics, baselines, numbers in docs | `eval-statistician` |
3. Each writes `domain.md | architect.md | specialist.md` (<= 400 words, evidence required).
4. Orchestrator writes `decision.md`: chosen option, why, dissent noted, tests that will prove it, reversibility. Conflicts -> choose the **safer and more reversible** option; if the choice is irreversible and still unresolved -> add to the batched human question list.
5. Append an ADR to `docs/DECISIONS.md`. Then implement.
**Question template**
```
# Consult NNN: <topic>
Context: <phase/feature; 3 lines; links to files>
Question: <one precise question>
Options considered: A) ... B) ... (C)
Constraints: FalkorDB v4.22.1 pinned; no Docker on dev box; no card; disk limited; deadline <time IST>
What I already tried / verified: <commands + outputs>
Decision needed by: <time>
Answer format: <= 400 words: Answer | Evidence | Confidence V/D/U | Risks | What would change my mind
```
**Cost control:** consults are for doubt, not decoration; skip when the answer is already in the tech docs (cite the line). Cap: 4 consults per phase unless a blocker.

## 5. Evidence log formats
`docs/PROGRESS.md` - top block **CURRENT STATE** (overwritten): phase, last green commit, next 3 actions, blockers, human-pending items. Below, append-only entries:
```
### <YYYY-MM-DD HH:MM IST> | Phase P | F-nn <title> | STATUS: done|blocked|cut
- Spec: docs/features/F-nn-*.md   - Commit: <sha>
- Tests: <command> -> <pass/fail counts> (exit 0)
- QA: docs/qa/F-nn.md PASS | Red-team: docs/qa/redteam-F-nn.md PASS|n/a
- Consults: docs/consults/NNN-* (decision summary)
- Numbers produced: <csv file(s)> | none
- Next: ...
```
`docs/DECISIONS.md` ADR: `ADR-NNN | date | Title | Context | Decision | Alternatives | Consequences | Evidence (consult id / test)`. Written in plain words - the human must be able to defend each ADR to a judge.
`docs/FEATURES.md`: table feature -> status -> tests -> QA report (feeds the README "Status" table; do not claim features not listed as done).

## 6. Self-review checklist (builder) and QA checklist
- Cypher static, parameterised; labels/types constants; no f-string with user data (lint test).
- Tenant from token only; `graph_name()` single choke point; no tenant field in bodies/args.
- Limits: sizes, arrays, depth, rate, quota; timeouts on every query; `ro_query` for reads.
- Writes: one atomic query per unit; chunked <= 2000; idempotent; no MULTI/EXEC; unique ids; constraint violations handled.
- Errors: typed codes, no stack traces, correlation id; `not_in_graph` instead of silent empty.
- Logs/metrics: no tokens/text; new op has trace + metric.
- Tests: unit + integration (real DB) + property invariant (`check_invariants`) + one failure-injection test.
- Docs/contracts updated (OpenAPI example, MCP schema, README row).
**QA report template:** `Feature | Commit | Commands (verbatim) | Output excerpts | Adversarial cases (>=5, each with result) | Findings (severity) | Verdict | Residual risks`.

## 7. Stop conditions
Continue looping until one of:
1. Release DoD met and submission artifacts ready (then stop and hand the human the final checklist).
2. **Feature freeze** reached (Sun Oct 18 3:00 PM IST): after that only bug fixes, docs, video, blog, submission. Orchestrator checks `date` at each milestone.
3. A **human-only step** blocks progress: batch ALL pending human items into ONE message (format in section 8) and continue with unblocked work; if nothing is unblocked, stop and wait.
4. **3 failed fix cycles** on one issue -> consult -> still failing -> log in KNOWN_ISSUES, apply the cut order, move on.
5. Budget/time exhaustion: write CURRENT STATE precisely so a fresh session resumes (section 10).
Never stop merely because the context is long: compact, then resume from PROGRESS.md.

## 8. Human-only steps: batched message format
```
HUMAN INPUT NEEDED (batch N, <time IST>) - I am continuing with: <unblocked work>
1. <step> - why it is blocked - exact action - time estimate
2. ...
Reply format: "1: done" / "1: <value or decision>" (never paste secrets into chat; put keys in .env and say "done")
```
Human-only list: register on WeMakeDevs/submit form, Discord question, GitHub repo creation/push credentials, API keys (Gemini/Groq), FalkorDB Cloud/Render accounts and keys, recording/uploading the video, publishing the blog, final submit click, anything requiring identity or money.

## 9. Anti-fabrication rules (binding on every role)
1. Never claim a command was run or a test passed unless you ran it and have the output; paste excerpts.
2. Numbers in README/blog/video/slides come only from `docs/NUMBERS.md`; no script -> no number; no estimates dressed as measurements; `scripts/check_numbers.py` enforces.
3. Never invent URLs, versions, quotes, benchmark results, user counts, "production" claims. Verify URLs with WebFetch/curl before citing; mark [U] otherwise.
4. Third-party systems (Graphiti, Mem0, PACMI, kintsugi...) are described only from sources read and dated; baselines are labelled emulations.
5. Do not claim a feature in README unless it is in `docs/FEATURES.md` as done with tests.
6. Unflattering results are reported as is (including where SQLite ties, where over-approximation is large, where friction is high).
7. Never print or commit secrets; `.env` is git-ignored; `scripts/check_secrets.sh` runs in `make check`.
8. Disclose AI assistance accurately (tools, roles, what the human verified).
9. Hackathon rules: new work only; FalkorDB central; synthetic/own/public data; explainability for the human.
10. Recorded traces contain only your own build sessions and synthetic data; no third-party private data.

## 10. Long-run mechanics (context, resume, time)
- **Resume protocol (start of every session and after compaction):** read `docs/PROGRESS.md` CURRENT STATE and last 5 entries, `docs/05-PHASES.md` current phase, `git log --oneline -20`, run `make test-quick`, check `date` vs deadlines, then continue.
- Commit early and often; checkpoint tags per phase; never leave the tree red at the end of a work block.
- Keep each subagent task small and self-contained (spec path + acceptance tests); do not paste huge outputs - write them to files and cite the path.
- Use the built-in read-only `explore` subagent (OpenCode) for repo search if needed.
- Time boxes are guidance: if a phase runs > 1.5x, consult, then cut per the cut order.

## 11. OpenCode specifics (verified against https://opencode.ai/docs/agents/ and /plugins, /mcp-servers on 2026-10-15)
- Agents can be Markdown files in `.opencode/agents/` (project) or `~/.config/opencode/agents/` (global); **file name = agent name**; frontmatter: `description` (required), `mode` (`primary|subagent|all`), `model`, `temperature`, `steps`, `permission` (keys: `read edit glob grep list bash task external_directory webfetch websearch lsp skill question doom_loop`; values `allow|ask|deny` or glob maps where the last matching rule wins), `hidden`. `tools:` is deprecated (use `permission`). Alternatively define under `agent` in `opencode.json`.
- Primary agents: switch with Tab; subagents: invoked by the model via the Task tool or by `@name`. `permission.task` restricts which subagents an agent may launch (glob patterns, e.g. `"*": deny` then allow list). Built-in subagents: `general`, `explore`, `scout`.
- Plugins: `.opencode/plugins/*.{js,ts}` auto-load; hooks `tool.execute.before/after` and events (`session.idle`, ...). MCP: `opencode.json` `mcp` block (`type: local|remote`, `command` array, `environment`, `enabled`, `timeout` default 5000 ms; remote: `url`, `headers`, `oauth`).
- **[U] T3 Code:** this pack assumes T3 Code passes through to OpenCode's agent/Task features; if `@orchestrator`/subagents are not available there, use the fallback below.

## 12. Fallback if subagents are unavailable (T3 Code, Antigravity, other)
1. **Role files as prompts:** each `opencode-agents/<role>.md` body is a stand-alone role prompt. Keep copies in `docs/roles/`.
2. **Sequential role-switch ritual (single agent):** for each consult/QA step the agent (a) writes the question file, (b) states "ROLE SWITCH: <role>. I will now ignore my previous reasoning and follow only the role prompt and the evidence in files," (c) re-reads the role prompt, (d) produces the artifact **by re-running commands, not by reasoning from memory**, (e) switches back and logs. It is weaker (shared context) so add one rule: QA must re-run every command in a **fresh shell** and must try adversarial cases the builder did not write.
3. **Multiple sessions (preferred fallback):** the human opens a new chat/thread per role (Antigravity's multi-agent/manager view if available **[U]**), pastes the role prompt + path to the question file; the orchestrator session waits for the file to appear (`ls docs/consults/NNN-*`).
4. **Parallel consults** become three sequential passes; the independence rule stays: each pass reads only `question.md` and evidence, not the other consultants' files, until all three exist.
5. Everything else (tests, evidence logs, DoD, numbers rule) is tool-independent.
