# 00 - Hackathon brief: WeMakeDevs x FalkorDB "Graph Hacks: Context for AI Agents"

Fetched and re-verified 2026-10-15 ~17:50-18:30 IST. Status labels: **[VERIFIED]** = read on the cited page; **[INFERRED]** = my reading; **[UNVERIFIED]** = could not confirm.

## 1. Core facts
| Item | Value | Source |
|---|---|---|
| Name | Graph Hacks: Context for AI Agents (powered by FalkorDB) | https://www.wemakedevs.org/hackathons/falkordb |
| Dates | Oct 15 2026 12:01 AM IST -> Oct 18 2026 11:59 PM IST (submissions close at the end of that window) | https://www.wemakedevs.org/hackathons/falkordb/rules , /schedule |
| Format | Online, worldwide, free to enter | main page |
| Team size | Solo or up to 4; one team per participant | rules #1 |
| Prize pool | $20,000 total | main page |
| Registration | Via WeMakeDevs account ("Register now"); team + submission managed from the same panel. Registrant count NOT visible (panel renders "Loading..."). **[UNVERIFIED]** | main page FAQ |
| Support | FalkorDB Discord open all event (https://discord.com/invite/Y2mMT9VdMy); WeMakeDevs Discord https://discord.gg/wemakedevs | main page, /resources |
| Submit page | https://www.wemakedevs.org/hackathons/falkordb/submit renders only "Pulling up this hackathon" for non-logged-in fetch, so the exact form fields are **[UNVERIFIED]**. Rules #10 lists required content (see section 4). | /submit |

## 2. Tracks and prizes (one prize per track + 2 side prizes)
1. **Agents That Act on Connected Data** -> iPhone 18 Pro. Focus: multi-hop reasoning, graph queries/algorithms as agent tools, tool selection through MCP, actions based on what the graph shows, explainable results. Examples named: investigate fraud, triage security findings, work through a codebase.
2. **Agent Memory and Coordination** -> PS5 with GTA VI. Focus: episodic/semantic/procedural memory, persistent history, shared state + handoffs between agents, high-concurrency reads/writes, separate memory per user or tenant.
3. **Company Brain** -> M6 Mac Mini. Focus: knowledge from docs/tickets/chats in one graph, who owns/knows what, tracing decisions to source, keeping knowledge current, answers with clear sources.
- Side: **Best blog post** -> AirPods 5. **Top 50 submissions** -> t-shirt for every member.
- "Every member of a winning team gets the prize." (rules #14)
- Source: main page + rules.

## 3. Rules that matter (paraphrased from https://www.wemakedevs.org/hackathons/falkordb/rules)
- FalkorDB must be the **primary** graph DB and support a **central** part of the product (#2).
- **Graph must do real work**: "if the product still works once FalkorDB is taken out, the graph is decoration" (#3). Docker, self-hosted, or FalkorDB Cloud all accepted (#4).
- You **must name every track you enter** when you submit; you may enter any or all (#5).
- Data must be **public, synthetic, or your own**; no private/login-protected/paywalled/personal data in the graph (#6).
- **Main coding and design work must begin after the start**; notes, sketches, diagrams beforehand are fine (#8). Frameworks/libraries/public APIs/datasets OK; "the original work completed during the hackathon will be judged" (#9).
- Submission must include (#10): public repo; README with setup + **graph data model**; the **Cypher queries or graph algorithms** the product depends on; **demo video**; **live deployment, or complete local setup instructions** if it can't be deployed; the track(s).
- **AI coding assistants allowed but must be DISCLOSED** (#11). Participants must **understand the code** and explain graph model, queries, architecture, decisions (#12). Projects "entirely generated using AI without meaningful participant contribution, verification, or technical understanding may be rejected" (#13).
- Plagiarism / manipulating judging => disqualification (#17). Rules/schedule/prizes "may be updated" (note at bottom).
- FAQ (main page): live deployment **preferred**; otherwise local setup + working demo video. Continuing an existing project: general libs/templates/infra OK, but "the submission and its main FalkorDB implementation must be new work completed during the event".

### Ambiguity to resolve (ask on Discord / check the submit form)
- Rules #5 and the FAQ say you may enter 1, 2 or all 3 tracks, each with its own prize. But the organizer's launch blog says "You enter one track, and one submission is judged in it" (https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph). **Conflict [UNVERIFIED which governs].** Safe plan: enter at most 2 tracks, both genuinely defensible, and ask the organizers in Discord today.

## 4. Submission checklist (derived from rules #10-#13 + FAQ)
- [ ] Public GitHub repo created **after Oct 15 00:01 IST** (first commit timestamp is public evidence). LICENSE file. No secrets committed.
- [ ] README: what/why, architecture diagram, **graph data model** (labels, edge types, properties), setup (Docker one-liner), env vars, how to run tests.
- [ ] A section "Cypher & algorithms we depend on" listing every query/procedure with a one-line purpose (e.g. variable-length reachability, `algo.SPpaths`, `algo.pageRank`, WCC, `GRAPH.COPY`).
- [ ] "If you remove FalkorDB" statement: why the product breaks (judging rule #3).
- [ ] Demo video (<= 3 min recommended; WeMakeDevs' other events use a 3-minute demo - https://www.wemakedevs.org/blogs/first-commit-hackathon-recap-and-whats-next).
- [ ] Live deployment URL (preferred) + fallback local setup that works from a clean clone.
- [ ] Track(s) named explicitly.
- [ ] AI-assistance disclosure file (which tools, what they wrote, what you verified) and be able to explain every query.
- [ ] Blog post (AirPods side prize). Where/how to submit the post is **[UNVERIFIED]** (rules do not say); publish on dev.to/WeMakeDevs blog and link from README and, if the form has a field, the form.
- [ ] Data statement: synthetic/own/public only.

## 5. Judging: what is actually published
- **No formal rubric or judge list is published** on the event pages (checked main, /rules, /schedule, /resources). **[VERIFIED absence]**
- The only judging guidance is the organizer's launch blog, section "What Judges Are Looking For" (https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph):
  - "In all three tracks the judging comes back to whether the graph is doing work the agent could not do without it." A graph that is "a store the agent occasionally reads from" "reads immediately" as any-database.
  - Strongest demo move: run the same question at depth 1 vs depth 4 so the multi-hop answer visibly exceeds what a join gives; show the path.
  - Second: let the agent say "not in the graph" (distinguish "no impact" from "not modelled") instead of always answering.
  - Design points the blog models: fixed tool catalogue of human-written parameterised Cypher exposed via MCP (the LLM never writes Cypher), arguments validated against the graph, sentence checked against returned rows, trace shows tool/args/ms/rows.
- Analogous WeMakeDevs judging (First Commit hackathon, AWS-specific): real-world impact, usability, working execution, 3-minute demo video (https://www.wemakedevs.org/aws/first-commit). Treat as a hint of the organizer's taste, not as this event's rubric.
- **[INFERRED] likely weights:** graph necessity + explainability (path shown) > working live demo > real-world relevance > polish/UX > code quality/tests. Judges are probably FalkorDB + WeMakeDevs staff (names unpublished).

## 6. What past/other WeMakeDevs events show
- First Commit (Sep-Oct 2026) winners recap: first prize Suraksha (an agentic companion for an aging parent), second prize Beacon (an on-call agent for the 3 AM page) - https://www.wemakedevs.org/blogs/first-commit-hackathon-recap-and-whats-next. Pattern: concrete, human-legible problems with working demos beat abstract tooling. **[INFERRED]** => our demo must lead with a concrete story, not with 'provenance graph'.
- I did not find published winners of earlier FalkorDB-sponsored WeMakeDevs hackathons in a few searches. **[UNVERIFIED]**

## 7. Competition snapshot (see 06-competitor-census.md)
- Participant count: not visible. Proxy: at least **~61 public GitHub repos** tagged to this event were created between ~Oct 14 18:31 UTC (event start) and Oct 15 ~12:20 UTC (~18 hours), found with one keyword search; true number is higher.
- A cluster of **at least 6-8 entries already target "repair/invalidate/provenance for agent memory"** (kintsugi, undograph, lineage, honest-memory, ripple, shaky-ground, accesscut, agentmesh). Roughly **a dozen are blast-radius / root-cause / impact clones** of the organizer's demo.

## 8. Risks (ranked)
1. **Crowding in the "poisoned/stale memory repair" idea space** (above). Mitigation: differentiate on real capture, confidentiality+integrity, gate wired into real agent hooks, honest evaluation (see 02, 03, 04).
2. **Originality / "new work" rule**: start a fresh repo now; do not reuse earlier code for the FalkorDB part; keep commit history clean; no copying of other entries (plagiarism rule).
3. **AI-generated-code rule**: judges may reject code the builder can't explain. Plan 30+ min to walk every Cypher query and the graph model; keep a DECISIONS.md written in your own words.
4. **Live deployment**: FalkorDB Cloud Free is 100 MB RAM / 100 MB max dataset, no credit card required, and **no TLS** on the free tier, though multi-graph and Graph Access Control are included (all **VERIFIED** at https://docs.falkordb.com/cloud/tiers/free). So the app<->DB link is plaintext: acceptable for synthetic demo data only, say so in the README; another entrant hit the same wall (https://github.com/Tejas-Sands/undograph). Reliable alternative: run FalkorDB in Docker on the same host as the API (Render free cannot run a persistent Docker DB for free - **[UNVERIFIED]**), or ship local Docker Compose + video as the primary artifact (FAQ allows it). Render free web service spins down after 15 min (https://render.com/docs/free) - pre-warm before judging, and keep the demo video as the primary artifact.
5. **Demo video quality** - rules require it; many projects fail here. Script in 04.
6. **Track ambiguity** (section 3).
7. **Free-tier LLM quotas** shrink during peak hackathon load (see 04 section 6); keep the core deterministic.
8. **Blog prize**: submission path unverified; do not leave to the last hour.
