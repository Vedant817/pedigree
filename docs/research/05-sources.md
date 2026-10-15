# 05 - Sources (all URLs used). Accessed 2026-10-15 IST. HTTP 200 checked for most; "secondary" = third-party summary.

## Event (primary)
- https://www.wemakedevs.org/hackathons/falkordb  (main page, tracks, prizes, FAQ; raw copy: page.html)
- https://www.wemakedevs.org/hackathons/falkordb/rules
- https://www.wemakedevs.org/hackathons/falkordb/schedule
- https://www.wemakedevs.org/hackathons/falkordb/resources
- https://www.wemakedevs.org/hackathons/falkordb/submit  (does not render form for logged-out fetch)
- https://www.wemakedevs.org/blogs/how-to-build-an-agent-that-reasons-over-a-graph  (organizer launch blog: judging guidance, Blast Radius demo, MCP/fixed-Cypher pattern, "enter one track")
- https://discord.com/invite/Y2mMT9VdMy  (FalkorDB Discord);  https://discord.gg/wemakedevs
- https://www.wemakedevs.org/aws/first-commit  (analogous WeMakeDevs judging criteria)
- https://www.wemakedevs.org/blogs/first-commit-hackathon-recap-and-whats-next  (winners recap)

## FalkorDB / platforms
- https://docs.falkordb.com/cloud/tiers/free  (100 MB, no card, no TLS, multi-graph, graph access control)
- https://docs.falkordb.com/agentic-memory ; https://docs.falkordb.com/agentic-memory/cognee
- https://github.com/FalkorDB/FalkorDB-MCPServer ; https://github.com/FalkorDB/GraphRAG-SDK ; https://github.com/FalkorDB/falkordb-py
- https://hub.docker.com/r/falkordb/falkordb
- https://render.com/docs/free  (spin-down after 15 min idle)
- https://console.groq.com/docs/rate-limits  (gpt-oss-120b/20b, qwen: 30 RPM / 1K RPD / 8K TPM / 200K TPD)
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://openrouter.zendesk.com/hc/en-us/articles/39501163636379-OpenRouter-Rate-Limits-What-You-Need-to-Know  (secondary via search; 20 RPM, 50 RPD free)
- https://klymentiev.com/blog/free-llm-api ; https://freetheai.org/blog/free-llm-api-comparison  (secondary)
- https://docs.claude.com/en/docs/claude-code/hooks ; https://opencode.ai/docs/plugins

## Prior art - systems
- Graphiti/Zep: https://github.com/getzep/graphiti ; https://arxiv.org/abs/2501.13956 ; https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py ; https://github.com/getzep/graphiti/blob/main/mcp_server/README.md ; https://github.com/getzep/graphiti/pull/261 ; https://github.com/getzep/graphiti/commit/9960ff2a12d46eff4329ae2f634f22e244640018 ; https://github.com/getzep/graphiti/issues/1331 ; https://github.com/getzep/graphiti/issues/1676
- Cognee: https://github.com/topoteretes/cognee ; https://docs.cognee.ai/core-concepts/main-operations/forget ; https://docs.cognee.ai/setup-configuration/community-maintained/falkordb ; https://www.cognee.ai/ai-memory-tools-vs-databases (vendor)
- Mem0: https://github.com/mem0ai/mem0 ; https://arxiv.org/abs/2504.19413 ; https://mnemoverse.com/docs/library/agent-memory-deduplication (secondary)
- Neo4j Agent Memory: https://neo4j.com/labs/agent-memory/ ; https://neo4j.com/labs/agent-memory/how-to/audit-reasoning/ ; https://github.com/neo4j-labs/agent-memory
- Letta: https://github.com/letta-ai/letta ; https://www.letta.com/blog/context-repositories/ ; MemGPT https://arxiv.org/abs/2310.08560
- A-MEM: https://arxiv.org/abs/2502.12110
- LangGraph: https://langchain-ai.github.io/langgraph/ (not re-read)

## Research on provenance / invalidation / IFC
- PACMI: https://arxiv.org/html/2610.05732v1 ; https://arxiv.science/abs/2610.05732
- Belief revision & TMS overview: https://cse.buffalo.edu/~shapiro/Papers/br-overview.pdf
- MemoRepair: https://arxiv.org/abs/2605.07242 ; https://arxiv.org/pdf/2605.07242v1/__stdout.txt
- MAP-Graph: https://arxiv.org/abs/2608.10509
- Governed Shared Memory: https://arxiv.org/html/2606.24535
- Non-malleable origin-bound authority: https://arxiv.org/html/2606.24322v1
- CaMeL: https://arxiv.org/abs/2503.18813 ; FIDES: https://arxiv.org/abs/2505.23643
- MAST: https://arxiv.org/abs/2503.13657

## Threats / incidents
- OWASP Agentic Top 10 2026 (ASI06): https://genai.owasp.org/download/52117/
- OWASP Agent Memory Guard: https://owasp.org/projects/agent-memory-guard
- MINJA: https://arxiv.org/abs/2503.03704 ; AgentPoison: https://arxiv.org/html/2407.12784
- Rehberger: https://embracethered.com/blog/posts/2025/gemini-memory-persistence-prompt-injection/ ; https://embracethered.com/blog/posts/2024/llm-context-pollution-and-delayed-automated-tool-invocation/ ; https://embracethered.com/blog/posts/2024/chatgpt-macos-app-persistent-data-exfiltration/
- Rules File Backdoor: https://www.pillar.security/blog/new-vulnerability-in-github-copilot-and-cursor-how-hackers-can-weaponize-code-agents ; scanner https://rule-scan.pillar.security/
- MCP tool poisoning: https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks ; https://invariantlabs.ai/blog/introducing-mcp-scan ; https://github.com/invariantlabs-ai/mcp-injection-experiments

## In-event competitors (GitHub; see 06-competitor-census.md and competitors/)
- https://github.com/Itz-Agasta/kintsugi ; https://github.com/Tejas-Sands/undograph ; https://github.com/Vaibhaav-Tiwari/lineage ; https://github.com/retailbox-automation/honest-memory ; https://github.com/MOHITPRADHAN35/agentmesh ; https://github.com/AI-conn/crew-memory-graph
- GitHub search used for the census: https://github.com/search?q=falkordb&type=repositories&s=updated (created >= 2026-10-14)

## Items I could NOT verify
- Registrant/participant count; official judging rubric; judge identities; exact submit-form fields; blog-prize submission mechanics; which track-count rule governs; FalkorDB ACL/concurrency/EXISTS-subquery behaviour on your pinned version (test locally); Mem0 current OSS behaviour; Mistral free-tier limits.
