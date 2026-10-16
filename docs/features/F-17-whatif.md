# F-17: what-if revocation (implemented subset)

Scope: docs/01-IDEA.md section 6.7 and docs/05-PHASES.md AT3.1. This feature previews revoking roots against a GRAPH.COPY, runs the real revoke engine, reports status/action differences, and deletes the temporary copy without changing the original graph.

Implemented interfaces: POST /v1/whatif and pedigree_whatif MCP tool. The engine accepts one to five roots, matching the docs/01 interface table. Roots are validated before copying and deduplicated. Response contains roots, revocations, diff (would_taint/would_preserve/would_revoke/unchanged), counts, affected actions, irreversible actions, copy, copy_deleted and ms.

Acceptance criteria: preview matches real revoke; original nodes/edges remain unchanged; copies are cleaned after successful and failed work; cleanup status is truthful; at most two active or pending-cleanup copies per tenant in a process (a global multi-worker cap remains unverified); stale copies older than ten minutes are reaped without deleting active work; REST/MCP resolve the tenant credential and reject mismatches/invalid roots. DB-dependent verification must use a real local FalkorDB; injected copy/delete errors must be labelled fault injection.

Checkpoint/restore is UNBUILT and excluded from the implemented subset. No checkpoint API, restore path, contamination-islands UI, deployment, or performance claim is implied. Cleanup, age handling and concurrency criteria are requirements pending independent verification, not claims that current code satisfies them.
