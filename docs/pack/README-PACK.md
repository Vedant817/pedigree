# Pedigree starter pack (WeMakeDevs x FalkorDB "Graph Hacks: Context for AI Agents")

**Pedigree = git blame + git revert for what an AI agent believes.** This pack lets an OpenCode (T3 Code) / Antigravity agent build, test, evaluate, document and deploy the whole project over 1-2 days while you do only the human-only steps. Event: Oct 15 12:01 AM -> **Oct 18 11:59 PM IST**. Our plan: feature freeze **Sun 3 PM**, submit **Sun 9 PM**.

## Do this, in order (about 15 minutes before the agent starts)
1. Read `00-HUMAN-CHECKLIST.md` top to bottom once. Do steps 1-6 now (register, Discord question, repo, `.env`); the rest can wait for the agent's first "human batch" message.
2. Unpack this folder (e.g. `~/pedigree-pack`). Open OpenCode in an **empty directory** (or the empty git repo you created).
3. Paste **`06-MASTER-PROMPT.md`** (entire file) as the first message. It is self-contained and tells the agent to read 01-05, 09 and to create the repo skeleton, copy the agents into `.opencode/agents/`, start FalkorDB v4.22.1 without Docker, and begin Phase 0.
   - If the agent cannot see the pack folder, paste `FALKORDB_PEDIGREE_PACK.md` (all of 00-09 in one file) instead.
   - If the context window is small, paste `07-KICKOFF-SHORT-PROMPT.md` (it makes the agent read the files itself).
4. Walk away. When it messages you with a **human batch**, do the listed steps, answer once, and tell it to continue. Use the "agent is stuck" table at the end of the checklist when needed.
5. From Sun 3 PM: follow the T-minus schedule in the checklist (video, blog, deploy check, submit).

## Files
| File | What / when |
|---|---|
| `00-HUMAN-CHECKLIST.md` | **You.** Human-only steps in order with time estimates, exact Discord message, keys, deploy, submission, blog venue, video tips, AI-use disclosure text, T-minus schedule, unstick prompts |
| `01-IDEA.md` | Full product spec: problem, scope, data model, every Cypher query/algorithm, MCP + REST contract, capture adapters, security |
| `02-ARCHITECTURE.md` | Components, repo layout, concurrency, deploy topology, threat model |
| `03-EVAL-AND-DEMO.md` | Experiments E1-E6 + baselines + statistics, scenarios, 3-min demo script, judge Q&A |
| `04-AGENT-OPERATING-SYSTEM.md` | How the agent works: roles, per-feature loop, QA gates, consult protocol, anti-fabrication, resume, fallback without subagents |
| `05-PHASES.md` | Feature list F-01..F-23 (priority, cut order), phases 0-5, acceptance tests, checkpoints |
| `06-MASTER-PROMPT.md` | **Paste-ready master prompt** |
| `07-KICKOFF-SHORT-PROMPT.md` | Short alternative that points at the files |
| `08-BLOG-TEMPLATE.md` | Blog outline (AirPods side prize), README template, demo shot list |
| `09-TECH-CHEATSHEET.md` | Verified FalkorDB / MCP / OpenCode / hooks facts, tagged [V] verified, [D] documented, [U] unverified |
| `FALKORDB_PEDIGREE_PACK.md` | 00-09 concatenated |
| `opencode-agents/` | 9 role agents (`orchestrator, builder, qa-senior, domain-researcher, senior-architect, red-team, eval-statistician, devex-reviewer, tech-writer`) + `opencode.json` + `common-rules.txt` + `INSTALL.txt` |
| `research/` | Hackathon brief/rules, track analysis, prior art, gaps, competitor census (00-06; `04-demo-and-eval-plan.md` is the earlier draft, **03 in this pack supersedes it**) |
| `tech/` | `TECH_REFERENCE.md`, `GOTCHAS.md`, `setup.sh`, `fetch-falkordb.sh`, `start-falkordb.sh`, `examples/` (incl. verified `12_pedigree_core.py`, `13_acl_tenant_isolation.py`, MCP servers + `mount_in_fastapi.py`), `bench/` raw outputs |

## Environment facts verified on 2026-10-15
- FalkorDB **v4.22.1** runs with no Docker: `tech/setup.sh` creates a venv (`falkordblite==0.10.0`, `falkordb==1.8.0`, `mcp` 2.x; ~160 MB), downloads the official 51 MB `.so`; `tech/start-falkordb.sh` starts it with `TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`. A clean-copy run of setup -> start -> `12_pedigree_core.py` + `13_acl_tenant_isolation.py` passed on the build box. No binaries are shipped in this pack (they are fetched).
- Never use FalkorDB `latest` (it is now a different, Rust 6.x engine). Pin v4.22.1.

## Decisions only you can make (details in the checklist)
1. **Tracks**: default Track 2 (Agent Memory) primary + Track 1 secondary; the rules and blog disagree on how many you may enter - ask on Discord (message provided).
2. Repo name (`pedigree`; alternates `pedigree-ledger`, `beliefblame`) and public-from-the-start.
3. Blog platform (the rules do not name one - ask in the same Discord message).
4. Which runtime to dogfood for the recorded demo trace (Claude Code hooks vs OpenCode plugin).

## Honest risks
- The "provenance / blame for agent memory" space has near neighbours (in-event entries named in `research/06-competitor-census.md`; academic PACMI, MemoRepair). Pedigree wins on engineering + evaluation + usability, not on claiming a new idea; the blog template is written that way.
- Unverified until the agent's Phase 0 spikes: single-container Render deploy (no Docker on the build box), OpenCode plugin `after`-hook payload, Claude Code matcher / `ask` values, whether T3 Code supports subagents (fallback documented in 04 section 12).
- FalkorDB Cloud Free: 100 MB, no TLS, no persistence - fallback demo DB only.
- The submission form fields and the blog venue are not published; the checklist marks them unverified.
