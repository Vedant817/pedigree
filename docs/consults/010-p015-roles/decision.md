# Decision: stored tenant roles, explicit operator invocation

Choose architect/specialist option A. Issue independent agent/operator credentials
with ped_a_/ped_o_ prefixes and only hashed storage. Resolve role from the matching
stored digest, never a claimed prefix. Legacy token_sha256 credentials retain agent
authority only. Keep credential.token as agent compatibility alias and return named
agent_token/operator_token on creation. Add explicit deployment-admin issuance/rotation
for an existing tenant; no silent startup privilege or unrecoverable digest reuse.

REST and MCP enforce the same capability boundary before mutation/quota acquisition:
agent may ingest/read/gate and agent corroborate; operator adds revoke/reinstate,
trusted Source claims and human/scanner corroboration. Reject explicit prohibited
assertions with forbidden, rather than silently downgrade. Events authorize the full
batch before any writes. Ordinary captured file/rules sources without a trusted claim
remain usable and untrusted; human/scanner kind assertions require operator. Global
X-Admin-Token never upgrades an agent bearer. Deployment-wide tenant create/list/resume
remain deployment-admin operations; no global tenant listing with a tenant operator.

Explicit operator MCP invocations are permitted. Shipped defaults/configs/hooks use
only agent credentials; reject configured operator defaults and hooked operator use.
This resolves C1's ambiguous 'MCP ... agent token only' in favor of its explicit
'agent ... via REST or MCP; operator token can' acceptance. Domain dissented in favor
of protocol-wide agent-only MCP. Record that dissent, test explicit operator behavior,
and document that an agent must never receive the operator credential.

HTTP MCP must consume Authorization Bearer using the actual installed SDK/ASGI
contract; malformed/invalid supplied credentials cannot fall back to a tool/default
credential. Conflicting header/tool identities or roles must fail closed. Preserve
in-process tool and stdio agent auth, no role state shared across concurrent calls.
Role-aware caches must recheck tenant active status. Indexed lookup/rate work remains
P-020; no unsupported O(1) claim here.

Proof: tests first for current agent revoke/trusted-claim failure, agent+valid admin
denial, operator REST/MCP success, prefix forgery, legacy downgrade, revoked/cross-tenant
denial, explicit/default precedence, header-only live HTTP MCP, whole-batch no-write
denial. Migrate positive operator tests, UI/demo credentials and dogfood without
weakening agent denials. Independent QA/red-team and full checks required.

Additive digest properties and explicit issuance are reversible, but reverting the
authorization boundary would restore the defect. No credential recovery from hashes.
Domain real-DB experiment validates property/null mechanics, not auth implementation.
