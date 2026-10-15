# 06 - Competitor census (public GitHub repos created since event start)

Method: GitHub repository search for "falkordb" and "Graph Hacks" limited to repos created since 2026-10-14T18:31Z (event start = Oct 15 00:01 IST), run ~2026-10-15 17:50-18:30 IST. Found ~61 unique repos. **Lower bound** (keyword search only; private repos and late starters invisible). Clustering is my judgement from repo names/descriptions/READMEs.

| Cluster | Approx. count | Repos (owner/name where known) |
|---|---|---|
| Blast-radius / impact / RCA / dependency | ~13 | blastradius (NishaadG), blast-radius (kushal), blast-radius (AgentAhmed), rootcause-agent, TraceFix, GraphSRE, Ripplemap, decisiongraph-ai, ChangeGraph, downstream, impactgraph, GraphPilot, gridpulse |
| Security / fraud / threat | ~7-8 | scout-falkordb, ThreatPath, Argus-SOC, graphhacks-refusal-agent, flowtrace, Financial_Crime_Agent, ghostgraph, lineagegate |
| **Memory repair / poisoning / provenance / invalidation (direct overlap)** | ~6-8 | kintsugi (Itz-Agasta), undograph (Tejas-Sands), lineage (Vaibhaav-Tiwari), honest-memory (retailbox-automation), ripple, shaky-ground, accesscut, agentmesh (MOHITPRADHAN35) |
| Generic agent memory / coordination | ~10 | recallgraph (dcain), recallgraph (alhassan), ContinuumAI, crew-memory-graph (AI-conn), second-brain, circe-graph, agent-office-relay, langgraph-enterprise-platform, nodus, ChronosGraph |
| Company brain | ~6-7 | company-brain-falkordb, node-and-nerve, threadline, bidbrain, who-said-what, Graph_Hackathon-Company-Brain |
| Health / other verticals | ~8 | dawaigraph, firstdomino, passthru, heatpath, eve, compgraph, bashi, gaming-multiverse-reasoner, official, OpenCyVer, codemind, orion |

(Counts overlap slightly; they do not sum exactly to 61.)

## Closest competitors (README scans saved in competitors/)
| Repo | What it claims | Signals from scan | How Pedigree differs |
|---|---|---|---|
| kintsugi (Itz-Agasta) | Repair poisoned shared memory in multi-agent system; walks provenance graph in FalkorDB; re-runs only affected actions on clean memory; stops where re-run yields same result; lists irreversible external effects; WIP (378-byte README) | Same thesis as our "revert list" and irreversible-effect listing; the *selective replay* idea is theirs | Real capture from live coding sessions; independent-support preservation; confidentiality labels; eval + isolation suite; shipped MCP/hook integration |
| undograph (Tejas-Sands) | Provenance + undo cascade on FalkorDB, with DESIGN.md | MCP=0 mentions; benchmark ~1 mention; no real-session capture; cloud deploy blocked on TLS | Same as above |
| lineage (Vaibhaav-Tiwari) | Company-brain unlearning with MCP, GRAPH.COPY, ACL, eval folder, mentions Claude Code (4x) | Most feature-complete; check whether "Claude Code" is capture or just client | Needs a closer read before Saturday; if it already captures real sessions, sharpen the confidentiality + eval angle |
| honest-memory (retailbox-automation) | Write-time checks for memory honesty | Write-time, not lineage | Complementary |
| crew-memory-graph (AI-conn) | Shared memory, tenants (7 mentions), benchmark (11 mentions) | Benchmark-minded rival on Track 2 | Our eval is about lineage/containment, theirs about memory sharing; read their benchmark to avoid duplicating |
| agentmesh (MOHITPRADHAN35) | Contradictions/races in shared memory | recall=2, race=2 | Different problem |

**Action item for the build:** re-run the census Saturday morning and Sunday morning (same search) to see if more provenance/repair entries appear; re-read lineage's repo and kintsugi's commits.
