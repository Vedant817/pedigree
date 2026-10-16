# Consult 010: agent/operator credentials and migration

Context: FIX_PROMPT.md Phase C1 / docs/fixes/P-015.md. P-014 quota changes are
verified and awaiting commit. Existing auth shares a tenant bearer; trust upgrades
currently require global X-Admin-Token, but revoke/reinstate remain agent-accessible.

Question: what minimal explicit credential/authorization contract closes operator
power on REST and MCP while preserving least-privilege legacy-token migration?

Options: A) two hashed role-prefixed tenant credentials with resolved role on every
request/tool; operator powers over REST and explicit operator-token MCP requests,
agent token in hook/default MCP configs. B) MCP categorically agent-only and reject
operator credentials there (conflicts with C1 operator-can acceptance?). C) retain
global-admin header for upgrades (reject unless defensibly compatible with C1).

Constraints: no paid providers, no secrets printed; FalkorDB v4.22.1 pinned, live
Docker DB available. Own only unique fixture graph/registry IDs and exact keys;
never enumerate/delete historical data. Static parameterized Cypher in queries.py.
No push/deploy. Legacy ped_<tenant>_<random> credentials become agent, never operator.
Keep O(1) digest-index work P-020 separate unless essential to schema safety here.
Timebox: answer in one bounded review; <=400 words with evidence, confidence,
risks, tests. Write ONLY your assigned consult file; no src edits.

Current observed contract: api/registry.py TenantCredential(tenant_id, token),
TenantRecord(id,status,node_cap,created_at); one token_sha property, SHA256 only,
resolve scans active rows and caches 30s. api/auth.py sets tenant only. MCP _resolve
returns (tenant,gname), authenticates explicit token or configured default token.
REST engine/events allow human/scanner trust with X-Admin-Token; MCP forbids those
claims outright. UI stores one bearer; CLI/admin/seeder mint one credential.

Context links: src/pedigree/api/{registry,auth}.py; api/routes/{admin,engine,events}.py;
src/pedigree/mcp_server.py; src/pedigree/db/{queries,schema}.py; src/pedigree/cli.py;
src/pedigree/api/static/; tests/security/test_capture_trust.py;
docs/consults/007-capture-trust/decision.md; FIX_PROMPT.md C1/C4.

Domain: verify role storage/migration mechanism with a short real-DB experiment
using a unique temporary graph, no credential values in output; domain.md.
Architect: explicit resolved-principal/API/MCP contract, migration/issuance and
test migration scope; architect.md.
Red-team specialist: laundering/role confusion/admin header escalation, legacy
prefix and default MCP attacks; specialist.md. Resolve the acceptance ambiguity
with a recommendation and note any dissent.
