# Domain: role storage and least-privilege migration

Recommendation: use two digest properties per tenant, resolving an explicit
`(tenant, role)` principal by digest equality. Prefixes are human-readable hints,
never authority. Preserve existing `token_sha` exclusively as agent authority;
issue a fresh operator credential through an authenticated administrative command.
Never manufacture an operator token by changing a legacy token's prefix.

Evidence: read `api/registry.py`, `db/client.py`, P-015 and FIX_PROMPT C1. Current
registry stores one SHA256 digest and scans active tenants. No additional graph,
dependency, or token-embedded role signature is necessary for this fix. Keep the
digest-index optimization separate for P-020.

Live PowerShell commands: `@'<Python below>'@ | .venv/Scripts/python.exe -`.
Python used `Db()` and a unique `consult_p015_<uuid>` graph, with random credentials
kept in memory. It created one legacy Tenant and executed twice:

```cypher
MATCH (t:Tenant {id:$id})
SET t.agent_sha=coalesce(t.agent_sha,t.token_sha),
    t.operator_sha=coalesce(t.operator_sha,$operator)
REMOVE t.token_sha
RETURN t.agent_sha,t.operator_sha,t.token_sha
```

The second call supplied a different operator digest. Actual output:

```text
legacy_missing_role_properties=True
legacy_agent_preserved=True
operator_digest_distinct=True
legacy_property_removed=True
migration_idempotent=True
digest_authority_agent_operator_forged_prefix=[True, True, False]
tenant_rows=1
owned_graph_cleanup=True
```

A separate `Db().client.connection.execute_command('MODULE','LIST')` inspection
printed `graph_module_version=42201`. Cleanup deleted only the generated graph;
no production registry writes occurred. This proves property/null/migration query
behavior, not application authorization, concurrent issuance, or crash-safe delivery.

Prefer compatibility reads of `coalesce(agent_sha,token_sha)` during rollout;
otherwise old rows stop authenticating before an explicit migration runs. A repeated
operator-issuance command must distinguish “already issued” from rotation: a stored
digest cannot recover the original bearer, and silently retaining an old digest
while returning a newly generated token produces an unusable credential. Rotation
must invalidate caches. Cache entries must carry role and reject inactive tenants.

Confidence: high for tested storage mechanics, medium for end-to-end migration
until real REST/MCP tests run. Test legacy agent acceptance, prefix forgery,
operator issuance/rotation, revoked tenant denial, and authorization before mutation.
FIX_PROMPT says MCP uses agent credentials; recommend agent-only MCP, with operator
acceptance demonstrated through REST/UI, explicitly recording that interpretation.
