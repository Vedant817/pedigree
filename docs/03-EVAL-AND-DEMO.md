# 03 - EVALUATION, DEMO, JUDGE PREP

**Rule zero: every number in README, blog, video and slides must come from a committed script that regenerates it (`make eval` -> `evals/results/*.csv` -> `scripts/extract_numbers.py` -> `docs/NUMBERS.md`).** No script, no number. Placeholders in this pack look like `⟦MEASURED: what⟧` and must be replaced from `docs/NUMBERS.md`, never typed by hand.
Machine/versions are recorded automatically in every results file (CPU, RAM, OS, FalkorDB module version, python, commit sha, seed).

## 1. What we evaluate and what each experiment can/cannot show
| ID | Question | Method | Cannot show |
|---|---|---|---|
| E1 | How much residual contamination / over-invalidation do common memory-repair semantics leave vs Pedigree? | Seeded synthetic lineage DAGs with built-in ground truth; 6 systems | End-to-end discovery of lineage (ground truth is built in) -> measures the **cost of the semantics**, not capture |
| E2 | How does capture fidelity change leakage and over-flagging? | Same DAGs; (a) precise capture with edge drop rate d in {0,1,2,5,10}%; (b) conservative read-window capture with K in {5,10,25,50,100} | Real-world window coverage (that is E6) - E2 is a model, say so |
| E3 | Do the 7 attack scenarios yield the exact expected contamination set, gate verdicts and revert lists? | Deterministic scripted scenarios replayed through the real API | Real attack success rates of the cited papers (we replay **patterns**, not their experiments); LLM-agent behaviour |
| E3b | **Gate friction on benign work** (false-block / reverify rate) | Replay recorded real sessions (E6 corpus) with no attack | Generalisation beyond the recorded sessions |
| E4 | Latency/throughput on FalkorDB: closure, revoke, blame, gate, what-if; tenants; concurrency | Sizes 1e3-1e6 nodes (cap by local disk/RAM), depth 2-12, K clients | Cloud Free performance (100 MB cap) |
| E4b | Is FalkorDB actually needed? | Same closure/revoke on SQLite recursive CTE (stdlib) vs FalkorDB BFS | Superiority at small scale (honest: SQLite may tie); report crossover |
| E5 | Tenant isolation and concurrency correctness | Property tests (hypothesis) + threaded stress + ACL test + invariant checker | Absence of all bugs |
| E6 | Real-trace case study (dogfooding) | Capture your own OpenCode/Claude Code sessions while building Pedigree; inject a planted canary source; hand-label 20 flagged actions | Statistical generalisation (n is small; report n) |

## 2. Baselines (implemented in `evals/baselines.py`; each is a documented emulation, not the vendor product)
| ID | Semantics | Basis |
|---|---|---|
| B0 | **Vector memory, delete-by-similarity:** delete items whose TF-IDF cosine to the bad source's text >= theta (theta calibrated on separate seeds; report the sweep) | typical vector store with no lineage |
| B1 | **First-provenance deletion** (Graphiti `remove_episode` semantics): remove items whose *first* provenance is the source; keep shared/derived items | https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py (re-read before quoting) |
| B2 | **Flat 1-hop:** invalidate direct children only | simplest provenance |
| B4 | **Full cascade without support check** (PACMI/MemoRepair-style withdraw all descendants) | https://arxiv.org/html/2610.05732v1 , https://arxiv.org/abs/2605.07242 |
| B5 | **Time-travel rewind:** invalidate everything created after the bad source (LangGraph-style checkpoint rewind) | recall 1.0 by construction, shows cost |
| P | **Pedigree:** cascade + independent-support preservation (+ barrier/fixpoint) | this repo |
(B3 temporal-only invalidation is omitted on purpose: with no supersession edges it detects nothing - including it would be a straw man.)

## 3. Metrics (definitions fixed before running)
Let G = items truly dependent on the bad source **without** independent support, H = all other items, A = affected actions.
`recall = |pred∩G|/|G|`, `residual = 1-recall`, `over_invalidation = |pred∩H|/|H|`, `precision`, `F1`, `action_recall = |pred∩A|/|A|`, `irreversible_recall`, `preserved_correct = |preserved ∩ should_preserve|/|should_preserve|`, `latency p50/p95/p99`, `throughput`, `friction = benign actions with verdict reverify|block / benign actions`.
**Statistics:** seeds `0..N-1` fixed in the repo (N>=30 per cell for E1/E2); report mean +- 95% CI (Wilson for proportions, bootstrap 10k resamples for means/percentiles); no seed cherry-picking; calibration (theta for B0) on disjoint seeds; report n for every cell; if variance is high, say so. The Eval Statistician agent signs off on `evals/REPORT.md`.

## 4. Generator spec (`evals/gen.py`)
Parameters: `S` sources (10-1000), `M` memories (100-100k) in `L` levels (1-8), fan-in `f` in 1..4, `p_corr` in {0,.1,.3} (probability a memory has an independent corroborating source), `A` actions (relying on 1-5 memories each, 20% irreversible), bad source chosen uniformly among sources with >= 1 descendant. Ground truth by the same recurrence as 01 §6.3 **implemented independently** in `evals/oracle.py` (brute-force fixpoint, different code from `engine/compute.py`; a test asserts both agree on small random DAGs).

## 5. Scenario suite (E3) - `demo/scenarios/*.json`, mapped to published classes
Each scenario file = ordered events + `bad_source` + `expected`: `{tainted:[...], preserved:[...], ok:[...], actions_affected:[...], irreversible:[...], gate:{step:verdict}}`.
| # | Scenario (pattern replayed, **not** the paper's experiment) | Source |
|---|---|---|
| S1 | Poisoned web page -> summary memory -> later commit + push | delayed-invocation memory poisoning https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/ |
| S2 | Another user plants a bridging record in shared memory; victim task later relies on it | MINJA class https://arxiv.org/abs/2503.03704 |
| S3 | Rules file with hidden-Unicode instruction; code generated under it; rules file revoked | https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents |
| S4 | MCP tool description changes after approval (hash differs) -> new Source -> outputs tainted | https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks |
| S5 | Sleeper memory: benign-looking memory written Monday (session A), triggers Friday (session B); cross-session link by `artifact_key`; plus an agent that **lies** via MCP (edge `agent_reported`) while the hook-captured window still catches it | AgentPoison, https://arxiv.org/abs/2407.12784 (memory-backdoor threat model; our scenario is a synthetic re-creation, not a reproduction) |
| S6 | **Confidentiality:** HR file -> summary memory -> asked to put it in a public README (`audience:['public']`) -> gate `block` with path | confused-deputy / FIDES-style labels https://arxiv.org/abs/2505.23643 |
| S7 | Stale decision: superseded source still driving a recommendation; revoke(kind=supersede) lists decisions to revisit | decision rot |
| S8 | **Independent support:** two memories from the bad page, one corroborated by a trusted doc -> `preserved`; its dependent stays `ok` | our contribution |
Also: invariant checker runs after each scenario (`check_invariants`).

## 6. Scripts to commit (each prints a one-line summary and writes CSV)
`evals/run_e1.py` (grid over L, f, p_corr, S, M; 6 systems) | `run_e2.py` | `run_e3.py` (replays scenarios through the HTTP API with a test tenant; asserts expected sets) | `run_e3b.py` (friction on recorded traces) | `run_e4.py` (+ `run_e4b_sqlite.py`) | `run_e5.py` (stress; also pytest-marked `slow`) | `run_e6.py` (ingest recorded sessions, canary injection, produces a hand-label sheet) | `evals/stats.py` (Wilson, bootstrap) | `evals/REPORT.md` (generated tables + plots + limitations; plots via matplotlib only if installed, else CSV + markdown tables) | `scripts/extract_numbers.py` -> `docs/NUMBERS.md` (each number lives under a heading `## <key>`; README/blog cite `⟦NUM:<key>⟧` and `scripts/check_numbers.py` fails if a cited key is missing or a number in README/blog is not in NUMBERS.md) (the **only** source for README/blog numbers) | `make eval` runs all with fixed seeds; `make eval-quick` runs a 2-minute subset for CI.
Disk-light: results are CSV/MD; no dumps committed; cap E4 at 1e6 nodes and record RSS.

## 7. Honest limitations (paste into README "Limitations")
- Pedigree **contains, explains and reverts**; it does not detect bad sources or prevent prompt injection.
- E1 has built-in ground truth: it quantifies baseline semantics, not lineage discovery. E2 is a model of capture error. E3 replays patterns, not the cited papers' experiments. E6 has small n.
- Session read-window capture over-approximates influence (ratio reported); `cite` edges tighten it but depend on agent cooperation (tagged `agent_reported`).
- `preserved` is only as good as the corroboration signal (explicit independent source asserted by agent/human/scanner).
- Hooks see only what the runtime exposes; paraphrase laundering through an unhooked channel is invisible.
- Bash risk classification is heuristic. External effects (pushes already pulled, emails sent) are listed, not undone.
- Cloud Free: 100 MB, no TLS, no persistence - hosted demo uses synthetic data only; benchmarks ran locally.
- B0-B5 are emulations of semantics described in public docs/papers, not the vendors' products.

## 8. Three-minute demo script (video; live if deployed)
Setup before recording: fresh tenant `demo`, scenario S1+S8 seeded **from a real recorded OpenCode session** (not hand-typed), UI open, terminal with the agent visible, 1440x900, font >= 16 px, captions on.
| Time | Screen | Say (own words; keep it this tight) |
|---|---|---|
| 0:00-0:20 | Agent (OpenCode or Claude Code) fixes a bug; Pedigree sidebar silently logging events | "Coding agents remember and act. When one source turns out to be bad, nobody can say what it already affected. Pedigree is git blame and git revert for what an agent believes." |
| 0:20-0:50 | Agent reads a web page and a rules file, writes a memory file, edits code, commits; graph grows live | "Hooks capture everything outside the model's control into FalkorDB: source, session, memory, action, commit. One graph per tenant." |
| 0:50-1:30 | Alert: the web page is malicious. Click **Revoke (dry run)**. Depth slider 1 -> 6: red wave; depth 1 shows 2 nodes, depth 6 shows ⟦MEASURED: N nodes incl. a commit and a push⟧ | "A join sees two things. The graph sees the commit six hops away." Click the commit -> blame path |
| 1:30-2:00 | Two memories turn green **preserved** (independently supported by the repo docs) | "Naive cascades delete these. Pedigree keeps what has independent support and shows why." Show bar chart ⟦MEASURED: over-invalidation B4 vs P⟧ |
| 2:00-2:25 | Agent attempts `git push`; gate blocks with the path. Ask `impact` on an id never recorded -> "not in the graph" | "The gate answers with evidence. Unknown is unknown, not 'safe'." |
| 2:25-2:50 | Eval table (E1/E2) + isolation test green + latency ⟦MEASURED⟧ | "Measured by committed scripts; tenant isolation tested against the failure class in Graphiti issues #1331/#1676." |
| 2:50-3:00 | Repo URL, tracks | "Tracks 2 and 1. All graph logic is Cypher on FalkorDB; remove it and nothing works." |
Record in 2 segments, rehearse 3x, keep a pre-recorded fallback clip per scene, upload to YouTube (unlisted is fine) and link in README and form.

## 9. Judge talking points
1. The graph is the product (rule 3): revoke/blame/gate/what-if are graph operations; tell them which procedures (`algo.BFS`, `algo.pageRank`, `GRAPH.COPY`, indexes, constraints, ACLs).
2. Multi-hop is visible: depth 1 vs depth N on screen (the organizer's own judging advice).
3. Fixed parameterised Cypher via MCP; the LLM never writes Cypher; `not_in_graph` is first-class.
4. Honest positioning: algorithm known (PACMI/MemoRepair/MAP-Graph); our contribution is capture, preservation, joint labels, isolation suite, measured results.
5. Production hygiene: tenant isolation (3 layers), auth, limits, timeouts, tests, metrics, resumable revocation.
6. Real data: dogfooded on the build sessions of this very repo.

## 10. Q&A prep (truthful answers)
1. **"Isn't this just a cascade delete over a DAG?"** The traversal is simple; the hard parts are capture, not over-deleting (independent support), the race between ingest and revoke, and tenant isolation. We measured each (E1, E2, E5). A recursive CTE can do the closure; E4b shows where the graph engine starts to matter [report whatever it shows].
2. **"How is it different from PACMI / MemoRepair / MAP-Graph / kintsugi / undograph / lineage?"** Same family; we credit them. Differences: out-of-band capture from real runtimes, preservation with measured over-/under-invalidation, integrity+confidentiality labels, tenant-isolation suite, resumable barrier protocol, reproducible attack scenarios. We did not claim a new algorithm.
3. **"How do you know lineage is complete?"** We don't; MemoRepair shows 1% missing edges can leak 17.7% (https://arxiv.org/pdf/2605.07242v1/__stdout.txt). E2 quantifies precise vs window capture; the window over-approximates on purpose; coverage in real sessions is E6 (small n).
4. **"Doesn't the window flag everything?"** It flags a superset; we report the over-approximation ratio ⟦MEASURED⟧ and the friction on benign sessions ⟦MEASURED⟧; `cite` edges narrow it.
5. **"Can a compromised agent forge lineage?"** Hook-captured edges are outside the model; MCP-reported edges are tagged and weighted lower; a compromised host can forge anything (stated).
6. **"Who decides a source is bad?"** A human, scanner or alert; Pedigree handles consequences.
7. **"What about effects that already left the machine?"** Listed as irreversible, not undone.
8. **"Why FalkorDB?"** Multi-graph = cheap tenant isolation (~0.4 MiB per graph [V]), BFS/PageRank procedures, `GRAPH.COPY` for atomic what-if, per-graph ACLs [V]. We tested on 4.22.1.
9. **"Who asserts independent support?"** The agent (via `corroborated_by`), a human, or a scanner; without a signal nothing is preserved (conservative).
10. **"Did AI write the code?"** Yes, assisted (AI_DISCLOSURE.md lists tools/roles). Be ready to walk every query in `queries.py`, the data model and the barrier protocol; DECISIONS.md is in your own words.
11. **"What do your evals NOT show?"** Section 7.
12. **"Cloud Free has no TLS?"** Correct (docs); hosted demo is synthetic data on loopback in a single container; local setup is the reference.
13. **"What if the hook is down?"** Fail-open by default (a stalled Claude Code hook does not block unless `onFailure:"block"`); events spool and replay; high-risk matchers can fail closed.
14. **"Why not just git?"** Git tracks files; we track beliefs, sources, confidentiality and the actions that relied on them across sessions and tools.
