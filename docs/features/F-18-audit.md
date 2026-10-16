# F-18: source influence audit (implemented subset)

Scope: docs/01-IDEA.md section 6.8 and docs/05-PHASES.md AT3.2. Rank status=ok Source nodes by algo.pageRank over Node/DERIVED_FROM, then pair each returned source with exact FEEDS BFS descendant reach. A PageRank score is a heuristic, not an exact count.

Implemented interfaces: GET /v1/audit/sources?limit=50 and pedigree_audit_sources MCP tool. Current response is {sources:[{id,kind,pagerank,descendants}],limit,note}; pagerank is null when the algorithm omits an eligible source (including edgeless graphs), and exact reach remains zero for an isolated source. This fallback does not invent a numeric rank; the engine clamps integer limits to 1..50. The initial interface table additionally lists status; current response omits it. Malformed noninteger REST limits should return validation errors. Public callers must not select another tenant via payload/tool arguments.

Acceptance criteria: known graph BFS counts match exactly, including isolated and shared descendants; only eligible sources appear; limits are bounded; empty graphs return no sources; REST/MCP wrong credentials and tenant mismatch are denied; audit does not mutate source data. Verify actual queries against local FalkorDB rather than claiming a source review proves runtime behavior.

WCC contamination islands, checkpoints and restore are UNBUILT and outside the implemented subset. Graph algorithm availability does not prove any UI or production behavior.
