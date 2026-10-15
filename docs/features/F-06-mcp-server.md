# F-06 - MCP server (stdio + Streamable HTTP)

Status: qa | Tests: `tests/integration/test_mcp.py` | QA: pending

## Behaviour
- `pedigree.mcp_server` builds an MCP server (`MCPServer` from the installed MCP SDK) with tools
  `pedigree_health`, `pedigree_record_source`, `pedigree_remember`, `pedigree_record_action`,
  `pedigree_corroborate`, `pedigree_revoke`, `pedigree_reinstate`, `pedigree_blame`,
  `pedigree_impact`, `pedigree_report`.
- `PedigreeMCPServer.run(transport, host, port)` supports `stdio`, `streamable-http`, `sse`.
- `pedigree mcp ...` CLI command constructs a server from `PEDIGREE_MCP_TENANT` /
  `PEDIGREE_MCP_TOKEN` (default: unresolved; tools accept per-call tenant/token).
- Transport JSON errors map `PedigreeError` codes to the engine contract. Tenant identity is resolved
  from bearer token before any graph name is computed.
- No duplicate logic: every tool calls the existing engine functions and respects
  `graph_name(tenant)`.

## Evidence needed
- pytest `tests/integration/test_mcp.py` green (2 tests).
- CLI `pedigree mcp --transport streamable-http --host 127.0.0.1 --port 8011` starts and answers /mcp.