# Consult 012: indexed role authentication and rate admission

Context: FIX_PROMPT C4 / docs/fixes/P-020.md. P-015 stored agent/operator roles,
legacy-agent compatibility and cross-process rotation/status checks are verified.
P-021 final checks are running; no P-020 implementation yet. This is Phase C's
fourth consult. Registry still scans all tenants on an uncached resolve, and REST
auth plus handlers charge writes twice; reads share write counts. MCP lacks matching
rate admission. Preserve fail-closed roles, token precedence and safe diagnostics.

Question: what minimal indexed digest lookup and one shared per-instance limiter
closes these defects without stale authority, duplicate charges or caller-spoofed IP?

Options: A) exact-match indexes on stored agent_token_sha256/operator_token_sha256/
legacy token_sha256 and static digest lookup queries, retaining stored-digest/role
checks and live invalidation. B) a startup digest dict plus refresh; discuss stale
cross-process revocation/rotation and O(N) refresh. Prefer measured DB behavior.

Rate proposal: one locked per-instance admission service injected into REST/MCP;
separate read/write buckets, writes counted once, revoke bucket additionally bounded.
Decide exact classification for gate/read-only POST/dry-run/what-if and failed requests.
Failed-auth backoff uses real transport peer IP, not supplied forwarding headers;
bounded per-process state and Retry-After. Stdio needs an honest local/session scope.
Define threshold boundary and any shared-IP denial tradeoff explicitly.

Constraints: pinned real FalkorDB42201 available; no paid providers, secrets, deploy
or push. Static parameterized Cypher only queries.py. Exact owned graph/registry IDs
and keys cleaned; never delete historical data. Synthetic bulk rows for latency/plan
tests should use a dedicated temporary registry graph, not pollute the real registry.
No benchmark marketing numbers; this is acceptance evidence, not NUMBERS publication.
No secret/digest values in output; token prefixes are hints, never authority.

Current files: src/pedigree/api/{registry,auth,app}.py; api/routes/{engine,gate,events,
workspace}.py; src/pedigree/mcp_server.py; db/{queries,schema}.py; diagnostics.py;
tests/security/test_p015_roles.py and test_p015_role_attacks.py; scripts/dogfood.py S20.
Registry.resolve cache hits recheck current stored digest/status by indexed tenant ID;
get_record/list_tenants retain TenantRecord; resolve returns ResolvedPrincipal+role.

Each writes ONLY domain.md / architect.md / specialist.md here, <=400 words with
recommendation, exact evidence, confidence, risks and acceptance tests. No source edits.
Domain: real indexed digest EXPLAIN/unknown-token probe at small/large synthetic size
and check old nullable slots, exact owned cleanup. Architect: minimal ownership and
integration/rate counting contract. Security specialist: cache revocation, role-prefix,
IP spoofing/shared-IP/backoff/state-growth/concurrency/MCP bypass attack matrix.
