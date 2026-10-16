# Security specialist: explicit principal, no ambient upgrades

Recommendation: option A. Resolve a tenant-scoped principal containing a verified
stored role on every REST request/MCP invocation. Prefixes describe credentials;
they do not confer authority. Match the complete token digest against its role's
stored slot. Unknown roles, mismatched prefixes/digests and revoked tenants fail
closed. Preserve legacy digest slots as agent only; never promote a legacy token
or mint an operator token during ordinary authentication.

Evidence (source review, high confidence): `api/auth.py:authenticate` retains only
tenant identity; `mcp_server.py:_resolve` does likewise. MCP revoke/reinstate and
REST equivalents currently accept that identity without a role check.
`routes/engine.py:operator_authorized` instead treats the deployment-wide admin
header as tenant trust authority. `routes/events.py` silently forces an agent's
claimed trust to untrusted; C1 requires an explicit 403. No new live attack was
executed for this consult; the required before/after transcript remains QA work.

Remove the admin-header upgrade path from tenant engine/events routes: agent plus
valid global admin header must still receive 403. Retain deployment admin only
for explicitly global administrative routes. Tenant operator powers must remain
within their own tenant, never list/create or resume another tenant.

Authenticate first, authorize before mutation. Preflight the entire normalized
events batch for forbidden trust assertions before session/source writes. A
caller-supplied runtime/kind/by/integrity or source identity cannot establish
authority. Agent `corroborated_by` must continue producing only agent edges;
existing operator attestations must survive agent retries without being created
or upgraded by them.

Resolve C1's MCP ambiguity by allowing an explicitly supplied operator token for
operator tools, while requiring agent credentials for configured MCP defaults
and hooks. Validate the default role at startup and invocation; never silently
fall back from an explicitly invalid token to a stronger default. This preserves
the operator-can acceptance without placing an operator secret in agent config.
Operator-in-agent-tool exposure remains a human configuration risk.

Required adversarial tests: agent revoke/reinstate including dry-run; direct and
batched trusted-source claims; human/scanner corroboration; agent plus valid
admin header; swapped prefixes and cross-tenant tokens; legacy-agent migration
and warm-cache role persistence; invalid explicit token with valid default;
operator default rejection; explicit operator success on both transports;
mixed valid/forbidden batch with zero mutations; complete laundering chain and
gate result before/after. Assert stored hashes, no raw secrets in responses/logs
except authorized one-time issuance, and no mutation on every denial.
