# 08 - BLOG TEMPLATE, README TEMPLATE, DEMO SHOT LIST

Rules for everything below: placeholders look like `⟦MEASURED: <what> -> docs/NUMBERS.md#<key>⟧`. Replace them **only** by copying from `docs/NUMBERS.md`. If a number does not exist yet, rewrite the sentence without it. Never round up, never invent. Write in the first person as Vedant; keep it honest, concrete and a little personal.

## Part 1 - Blog post: "How to un-poison an agent's memory"
**Target:** dev.to (default) / WeMakeDevs community blog. **Goal:** win the best-blog side prize (AirPods 5) - judged presumably on clarity, usefulness and showing real work (criteria unpublished [U]). Length 1,400-2,000 words, 6-9 images (screens/GIFs/diagrams), runnable snippets, link the repo + video at the top and bottom. Tags: `#hackathon #ai #security #graphdb #opensource`.
**Title options:** "How to un-poison an agent's memory (git blame for what your AI believes)" | "Your coding agent remembers things. Do you know where from?"

### Outline
1. **Hook (100 words, a concrete story):** an agent reads a web page, writes a note into `CLAUDE.md`/memory, commits code under it; later the page turns out to be malicious. "Which of my agent's beliefs, files and commits came from that page?" Nobody could answer. Cite one real incident class with a link (Rehberger's Gemini memory attack https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/ or Rules File Backdoor https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents).
2. **Why the usual tools can't answer it (150 words):** vector memory keeps no derivation; Graphiti-style `remove_episode` removes edges first sourced from an episode, not derived beliefs/actions (https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py; **re-read the code and quote only what you verified before publishing**); time-travel rewinds everything after a point. Frame: this is a **lineage** problem = a graph problem.
3. **What Pedigree does (150 words + 1 diagram + GIF):** capture -> graph -> revoke -> preserve -> gate. One sentence each. Credit prior art generously (PACMI, MemoRepair, MAP-Graph, CaMeL/FIDES, other entrants in this hackathon) and state the contribution honestly: capture from real runtimes, independent-support preservation, joint integrity/confidentiality labels, isolation suite, measured results.
4. **The graph model (200 words + table):** labels, edges (`DERIVED_FROM` + mirrored `FEEDS`, `CORROBORATED_BY`), statuses, per-tenant graph `ped:<tenant>`. Why mirror edges: `algo.BFS` follows one outgoing edge type; var-length `*1..k` explodes (cite your measured numbers: ⟦MEASURED: BFS vs var-length latency at depth k -> NUMBERS.md#bfs_vs_varlen⟧).
5. **The queries that matter (300 words, 3-4 snippets):** descendants by BFS; the atomic root revoke CAS; the chunked quarantine write; the confidentiality check. One sentence on why each is a graph operation. Link `docs/WALKTHROUGH.md`.
6. **The part that surprised me - races and "don't throw out the baby" (250 words):** barrier + fixpoint so a memory written *during* a revocation can't slip through (born-quarantined rule); independent support so two of ⟦MEASURED: N⟧ tainted memories survive. Show the over-invalidation chart ⟦MEASURED: over_invalidation B4 vs P -> NUMBERS.md#e1_over_invalidation⟧.
7. **Capture is the hard part (200 words):** hooks for Claude Code, plugin for OpenCode; MemoRepair's finding that 1% missing edges can leak 17.7% (https://arxiv.org/pdf/2605.07242v1/__stdout.txt) -> our E2 curve ⟦MEASURED: leak vs drop rate, window over-approximation -> NUMBERS.md#e2_*⟧ and what the read-window costs in friction ⟦MEASURED: friction -> NUMBERS.md#e3b_friction⟧.
8. **Demo walk-through (150 words + GIF):** the 3-minute story in prose.
9. **Honest limitations (150 words):** copy from docs/03 section 7 - do not soften (does not detect or prevent injection; E1 ground truth built in; E2 is a model; small-n real traces; heuristic bash classifier; Cloud Free no TLS).
10. **How to run it (100 words):** 4 commands; MCP/hook install; link repo.
11. **What I learned / what's next (100 words):** one real lesson (e.g. FalkorDB `MATCH` after `UNWIND` silently drops missing parents; `MULTI/EXEC` isn't atomic; ACL pattern `~ped:abc` vs `abcd`) - these are verified gotchas, they make the post useful. Closing line + links. 
12. **AI disclosure (2 sentences)** matching `AI_DISCLOSURE.md`.
**Quality checklist before publishing:** every number in NUMBERS.md (`scripts/check_numbers.py`) | all links open | every code snippet copy-pasted from the repo at a tagged commit | images readable at mobile width | no secrets in screenshots | first 3 lines work as a standalone summary | one clear call to action (try the repo / watch the 3-min video).

## Part 2 - README template (`README.md`)
```markdown
# Pedigree - git blame & git revert for what your AI agent believes
> Hackathon: WeMakeDevs x FalkorDB Graph Hacks | Tracks: <per ADR-000, default: Track 2 Agent Memory & Coordination + Track 1 Agents That Act on Connected Data>
[3-min demo video](<URL>) | [Live demo](<URL>) | [Blog post](<URL>)
![demo gif](docs/img/demo.gif)

## The problem (3 sentences + 2 sources)
## What Pedigree does (5 bullets: capture, revoke, preserve, gate, isolate)
## Why FalkorDB (and what breaks without it)
- Every operation below is a graph operation; remove FalkorDB and revoke/blame/gate/what-if do not exist.
- Uses: one graph per tenant (multi-graph), `algo.BFS`, `algo.pageRank`, `GRAPH.COPY`, indexes + unique constraints, per-graph ACLs.
## Quickstart (local, ~5 minutes)  [commands verified by scripts/clean_clone_check.sh]
## Install capture: Claude Code hooks | OpenCode plugin | MCP (config snippets)
## Graph data model (table of labels/properties/edges + diagram)
## Cypher & algorithms the product depends on (every query, one line of purpose each; link to docs/WALKTHROUGH.md)
## Architecture (mermaid) and consistency strategy (barrier + fixpoint, chunking, idempotent revocation)
## Security model (tenant isolation 3 layers, auth, limits, what is NOT covered)
## Evaluation (numbers ONLY from docs/NUMBERS.md; table + chart; how to reproduce: make eval)
## Honest limitations (verbatim from docs/03 section 7)
## Related work and how we differ (PACMI, MemoRepair, MAP-Graph, CaMeL/FIDES, Graphiti, Neo4j Agent Memory, agentblame; in-event: kintsugi, undograph, lineage - factual, generous, dated)
## Status (generated from docs/FEATURES.md)   ## AI disclosure   ## License (MIT)
```

## Part 3 - Demo video shot list (target 2:50-3:00)
| # | Time | Visual | Narration cue | Capture notes |
|---|---|---|---|---|
| 1 | 0:00-0:10 | Title card: "Pedigree - git blame for what your agent believes" + your name | one-line hook | static 3 s then cut |
| 2 | 0:10-0:30 | Split: terminal with the coding agent working; Pedigree UI "live events" ticker | "Agents remember and act..." | use the real recorded session replay if live is flaky |
| 3 | 0:30-0:50 | UI graph growing: Source -> Memory -> Action -> commit; hover shows `via` (hook vs agent-reported) | "captured out-of-band by hooks into FalkorDB, one graph per tenant" | zoom the legend |
| 4 | 0:50-1:30 | Click the malicious web Source -> Revoke (dry run) -> depth slider 1 then 6 -> red wave -> list: files, commit, push | "A join sees two; the graph sees the commit six hops away" | numbers on screen must equal NUMBERS.md |
| 5 | 1:30-2:00 | Preserved nodes turn green with the supporting source; bar chart B4 vs Pedigree | "independent support is kept" | show chart from evals/results |
| 6 | 2:00-2:25 | Agent attempts `git push` -> hook blocks, reason with path; `impact` on unknown id -> `not_in_graph` | "unknown is not safe" | show the JSON trace strip (tool/args/ms/rows) |
| 7 | 2:25-2:50 | Terminal: `make eval-quick` summary; tests green; isolation test; latency table | "reproducible; isolation tested against Graphiti issue class" | cut to pre-generated output if slow |
| 8 | 2:50-3:00 | End card: repo URL, live URL, tracks, "FalkorDB is the product" | CTA | hold 4 s |
Audio: voice-over recorded separately, normalised, no music. Subtitles on. Export 1080p MP4; also upload to YouTube unlisted.
