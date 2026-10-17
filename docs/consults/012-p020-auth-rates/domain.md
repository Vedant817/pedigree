# Domain recommendation

Use three operational exact-match indexes on `Tenant(agent_token_sha256)`,
`Tenant(operator_token_sha256)`, and `Tenant(token_sha256)`, with one static,
parameterized lookup in `queries.py`:

```cypher
MATCH(t:Tenant)
WHERE t.agent_token_sha256=$sha OR t.operator_token_sha256=$sha OR t.token_sha256=$sha
RETURN t.id,t.status,t.node_cap,t.created_at,t.token_sha256,t.agent_token_sha256,t.operator_token_sha256
```

Retain `_principal`'s stored-digest, active-status, complete tenant-prefix and role
checks. Refuse multiple tenant candidates. Prefixes select no authority. A single
fresh indexed lookup per resolution is simpler than a startup dictionary or cache
that still needs a live authority check; remove the scan and unnecessary cache.

## Observed evidence

Executed Python stdin probes using installed `Db`, `Graph.explain(query, params)`,
`wait_indexes`, parameterized `UNWIND` creation, and `GRAPH.LIST`. Actual module
version: **42201**. Dedicated random `p020_domain_<uuid>` graphs held **31**, then
**5,001** synthetic Tenant nodes; the actual registry was untouched. Three seed
rows each held only one credential slot; the other two properties were null.

For every individual equality lookup and the combined OR query, EXPLAIN returned:

```text
Results
    Project
        Node By Index Scan | (t:Tenant)
```

Each slot's synthetic known digest returned exactly one row at both sizes; unknown
digests returned zero. Null slots caused neither errors nor false matches. Fifty
sequential unknown-digest OR lookups per size measured local wall-clock median
**0.628 ms / 0.626 ms**, maximum **0.958 ms / 1.082 ms**. Individual-slot medians
ranged **0.775–0.811 ms / 0.769–0.907 ms**. These are noisy local acceptance probes,
not production latency promises or proof of mathematical constant time.

An intentionally duplicated digest across different tenant/role slots produced
**two candidates**, proving an ambiguity check is necessary. Indexes are not a
replacement for credential comparison and authorization.

All owned graphs were deleted; `GRAPH.LIST` confirmed exact final graph absence,
and a prefix count after the initial probe confirmed zero probe graphs remaining.
No tokens or digest values were printed. Initial cleanup verification used a
nonexistent `Db.graphs()` helper after deletion; corrected verification used
`Db.admin_raw('GRAPH.LIST')`.

Confidence: high for this pinned runtime's indexed mechanism; modest for timing.
Acceptance: assert indexed plans after migration, bounded query counts for misses,
nullable legacy compatibility, duplicate-candidate denial, revoked/rotated credentials
across processes, role-prefix mismatch denial, and no plaintext credential storage.
