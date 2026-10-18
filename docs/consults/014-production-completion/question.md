# Consult 014: production completion
Context: urgent release request requires all remaining capabilities, real persistence and live verification, no seeded production data. Read AGENTS.md, docs/KNOWN_ISSUES.md, config, db/client, registry, api/deps, MCP, capture adapters and deployment scripts as relevant.
Question: What is the smallest compatible production design for service-level tenant ACL enforcement, durable hook spool, checkpoint/restore and non-demo startup, and what must block release?
Constraints: preserve crashed pedigree-db volume, one graph per tenant, token-derived tenancy, no secrets printed, no existing user edits touched. Main release worktree is ../pedigree-release-20261018. You are read-only except your assigned consult artifact. Do not run graph-mutating tests on the old DB; fresh release DB will use 6381.
Answer: <=400 words with observed file/line evidence, concrete acceptance checks, uncertainty. Do not edit product code.
