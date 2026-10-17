# Security specialist recommendation

Choose indexed parameterized digest lookup, retaining live status/digest/prefix
verification. Confidence: high on the security contract; index-plan/latency proof
belongs to the domain probe, not this source review.

Evidence: `registry.py:130-157` scans all tenants on misses; `:136-145` already
revalidates cached authority against live rows. Preserve that property or remove
the cache entirely. `_principal` (`:160-178`) binds the stored digest slot to role
and complete tenant prefix; prefix guessing must never grant authority. Reject
ambiguous multi-row matches. A startup-only digest map permits stale cross-process
rotation/revocation. Bound successful-cache entries if retained; avoid negative
token caches containing arbitrary attacker identities.

`auth.py:22-38` uses unsynchronized deques and `:68` charges every authenticated
request as a write. `app.py:167` creates unbounded key state; MCP `_resolve`
(`mcp_server.py:197`) lacks equivalent rate admission. Inject one limiter into REST
and its mounted MCP server; standalone MCP owns one instance. Key authenticated
buckets by resolved tenant, shared across agent/operator credentials and protocols.
Classify before dispatch; charge once before protected work, including eventual
engine failures. Reads must not spend write quota. Revoke consumes write plus its
additional bucket atomically, with no partial charge if either is exhausted.

Use a lock around prune/check/append: N eligible requests succeed, N+1 is denied,
even across threads. Expire idle buckets and cap key count without evicting live
exhausted buckets into fresh allowances; refuse new keys safely when capacity is
full. Per-instance limits multiply across workers/restarts: document explicitly.

Failed-auth accounting must atomically return ten 401 outcomes, then 429 with a
bounded Retry-After; precheck exhausted peer buckets before expensive lookup.
Concurrent failures already in flight can still cause lookup work: do not claim
hard authentication-work admission from outcome accounting alone. Use actual ASGI
peer IP, ignore Forwarded/X-Forwarded-For, and prevent Uvicorn proxy rewriting unless
trusted proxy configuration is explicit. Shared-IP blocking can deny valid users
behind NAT after another user's failures; choose and document that tradeoff.
Stdio has no remote IP: use one server-local session scope, never caller tenant IDs.

Acceptance: warm-cache cross-process rotation/revocation; forged role prefixes and
legacy a_/o_ tenant names; unknown digests at registry sizes; concurrent N/N+1;
mixed REST/MCP read/write calls; dry-run/gate/what-if classification; malformed and
conflicting headers; forwarded-IP spoofing; same-stdio-session and reconnect
attempts; bounded state under many peer identities. Responses/logs must retain
P-021 redaction and P-015 authoritative-header precedence.
