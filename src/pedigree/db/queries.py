"""Static, parameterised Cypher. NOTHING in this module may interpolate user input.

The only string interpolation allowed is a node label taken from a fixed allow-list
(`_LABELS`); every literal value travels as a query parameter. A lint test
(tests/unit/test_queries_static.py) enforces that no other f-string/substitution exists.

P-010: id anchors are always written on the Node label
(`MATCH (x:Node {id:$v}) WHERE x:<Label>`) so the unique `:Node(id)` index
(`Q_INDEX_NODE_ID`) is used; anchoring the same lookup on the type label plans as a
Node By Label Scan and made the revoke cascade quadratic (AUDIT.md P-010).
Lint: tests/unit/test_query_lint.py; plan assertions: tests/perf/test_revoke_scaling.py.
"""

from __future__ import annotations

from ..errors import InvalidArgument

_LABELS = frozenset({"Source", "Memory", "Action", "Session", "Agent", "Revocation"})


def _label(name: str) -> str:
    if name not in _LABELS:  # pragma: no cover - programming error
        raise InvalidArgument("unknown node label")
    return name


# --- schema -----------------------------------------------------------------
Q_INDEX_NODE_ID = "CREATE INDEX FOR (n:Node) ON (n.id)"
Q_INDEX_TENANT_ID = "CREATE INDEX FOR (t:Tenant) ON (t.id)"
Q_INDEX_TENANT_AGENT_DIGEST = "CREATE INDEX FOR (t:Tenant) ON (t.agent_token_sha256)"
Q_INDEX_TENANT_OPERATOR_DIGEST = "CREATE INDEX FOR (t:Tenant) ON (t.operator_token_sha256)"
Q_INDEX_TENANT_LEGACY_DIGEST = "CREATE INDEX FOR (t:Tenant) ON (t.token_sha256)"
Q_INDEX_MEMORY_ARTIFACT = "CREATE INDEX FOR (n:Memory) ON (n.artifact_key)"
Q_INDEX_ACTION_ARTIFACT = "CREATE INDEX FOR (n:Action) ON (n.artifact_key)"
Q_INDEX_REVOCATION_ROOT = "CREATE INDEX FOR (n:Revocation) ON (n.root_id)"
Q_INDEX_REVOCATION_STATE = "CREATE INDEX FOR (n:Revocation) ON (n.state)"
#: Supporting exact-match indexes for the Source identity constraint (ADR-008). A uri-only
#: constraint is deliberately absent: it rejects a legitimately changed page (measured).
Q_INDEX_SOURCE_URI = "CREATE INDEX FOR (s:Source) ON (s.uri)"
Q_INDEX_SOURCE_HASH = "CREATE INDEX FOR (s:Source) ON (s.content_hash)"
Q_INDEXES = "CALL db.indexes()"
Q_INDEX_CAPTURE_ID = "CREATE INDEX FOR (r:CaptureReceipt) ON (r.id)"
Q_CAPTURE_GET = "MATCH (r:CaptureReceipt {id:$id}) RETURN r.digest, r.cursor, r.aliases, r.created, r.plans, r.created_at"
Q_CAPTURE_CREATE = """
CREATE (:CaptureReceipt {id:$id, digest:$digest, tenant:$tenant, cursor:0,
    aliases:'{}', created:'[]', plans:'{}', created_at:$now})
"""
Q_CAPTURE_ADVANCE = """
MATCH (r:CaptureReceipt {id:$id})
SET r.cursor=$cursor, r.aliases=$aliases, r.created=$created, r.plans=$plans
"""
Q_CAPTURE_ACTION = "MATCH (a:Node {id:$id}) WHERE a:Action RETURN a.capture_key"
Q_INV_CAPTURE_SHAPE = """
MATCH (r:CaptureReceipt)
WHERE r:Node OR r.digest IS NULL OR size(r.digest) <> 64 OR r.cursor IS NULL OR r.cursor < 0
    OR r.aliases IS NULL OR r.created IS NULL OR r.plans IS NULL OR r.created_at IS NULL
RETURN count(r)
"""
Q_CAPTURE_READ = """
MATCH (se:Node {id:$sess}), (n:Node {id:$n}) WHERE se:Session
MERGE (se)-[r:READ]->(n)
SET r.at = CASE WHEN coalesce(r.at,0) > $now THEN r.at ELSE $now END
RETURN n.id
"""
Q_WHATIF_STATUSES = """
MATCH (n:Node) WHERE n:Source OR n:Memory OR n:Action RETURN n.id, n.status
"""
Q_WHATIF_ACTIONS = "MATCH (a:Action) RETURN a.id, a.tool, a.summary, a.effect, a.risk, a.status"
Q_WHATIF_CREATE_LEASE = "CREATE (:WhatIfLease {owner:$owner, expires_at:$expires})"
Q_WHATIF_LEASE = "MATCH (m:WhatIfLease) RETURN m.owner, m.expires_at LIMIT 1"

# --- lookups ----------------------------------------------------------------
Q_FIND_IDS = "MATCH (n:Node) WHERE n.id IN $ids RETURN n.id, n.status"
Q_NODE_BY_ID = "MATCH (n:Node {id:$id}) RETURN n.id, labels(n), n.status, n.tenant"
Q_NODE_STATUSES = "MATCH (n:Node) WHERE n.id IN $ids RETURN n.id, n.status"

Q_ARTIFACT_LOOKUP_MEMORY = (
    "MATCH (n:Memory {artifact_key:$k}) WHERE n.status <> 'revoked' "
    "RETURN n.id, n.status ORDER BY n.created_at DESC LIMIT 1"
)
Q_ARTIFACT_LOOKUP_ACTION = (
    "MATCH (n:Action {artifact_key:$k}) WHERE n.status <> 'revoked' "
    "RETURN n.id, n.status ORDER BY n.created_at DESC LIMIT 1"
)

# --- create: sources (roots) -------------------------------------------------
Q_CREATE_SOURCE = """
CREATE (n:Node:Source) SET n = $props, n.created_at = $now
RETURN n.id, n.status, n.low_integrity, n.conf_eff
"""

# --- derived Source identity (consult 007 / ADR-008) --------------------------
# One node per (tenant, uri, content_hash): the composite unique constraint makes the MERGE
# atomic and idempotent, so repeated reads of the same artifact converge and the same uri with
# a new hash is a new version whose old hash stays revocable. A uri-only constraint is
# deliberately absent: it rejects a legitimately changed page (measured on v4.22.1).
Q_SOURCE_MERGE_HASHED = """
MERGE (n:Node:Source {tenant:$tenant, uri:$uri, content_hash:$hash})
ON CREATE SET n = $props, n.created_at = $now
RETURN n.id, n.status, n.low_integrity, n.conf_eff
"""
# Hash-less captures carry no content identity, so the key is a server-derived node id
# (sha256 of tenant|uri): the Node(id) unique constraint makes it atomic under concurrency,
# which a MERGE on (tenant, uri) alone is not - NULL content_hash is exempt from the pair
# constraint (measured: 10 concurrent MERGEs produced 50 nodes).
Q_SOURCE_MERGE_URI = """
MERGE (n:Node:Source {id:$derived})
ON CREATE SET n = $props, n.created_at = $now
RETURN n.id, n.status, n.low_integrity, n.conf_eff
"""
Q_SOURCE_BY_ARTIFACT = """
MATCH (n:Source {tenant:$tenant, uri:$uri, content_hash:$hash})
RETURN n.id, n.status, n.low_integrity, n.conf_eff
"""

# --- create with parents (Memory/Action): edge + mirror + flag inheritance in ONE query
_CREATE_WITH_PARENTS = """
CREATE (c:Node:{label}) SET c = $props, c.created_at = $now
WITH c UNWIND $parents AS pid MATCH (p:Node {{id:pid}})
MERGE (c)-[d:DERIVED_FROM]->(p) SET d.rel = $rel, d.via = $via
MERGE (p)-[:FEEDS]->(c)
WITH c, collect(p) AS ps
SET c.low_integrity = any(p IN ps WHERE coalesce(p.low_integrity, false) = true),
    c.conf_eff = reduce(acc = coalesce(c.conf, []), p IN ps | acc + [t IN coalesce(p.conf_eff, []) WHERE NOT t IN acc]),
    c.status = CASE WHEN any(p IN ps WHERE p.status IN ['revoked','tainted','quarantined']) THEN 'quarantined' ELSE 'ok' END
RETURN c.id, c.status, c.low_integrity, c.conf_eff, size(ps) AS n_parents
"""

# --- create without parents (unanchored): separate query (UNWIND [] yields no rows, GOTCHAS #16)
_CREATE_ORPHAN_MEMORY = """
CREATE (c:Node:Memory) SET c = $props, c.created_at = $now
RETURN c.id, c.status, c.low_integrity, c.conf_eff, 0 AS n_parents
"""
_CREATE_ORPHAN_ACTION = """
CREATE (c:Node:Action) SET c = $props, c.created_at = $now
RETURN c.id, c.status, c.low_integrity, c.conf_eff, 0 AS n_parents
"""


def q_create_with_parents(label: str) -> str:
    return _CREATE_WITH_PARENTS.format(label=_label(label))


def q_create_orphan(label: str) -> str:
    label = _label(label)
    if label == "Memory":
        return _CREATE_ORPHAN_MEMORY
    if label == "Action":
        return _CREATE_ORPHAN_ACTION
    raise InvalidArgument("only Memory and Action can be created without parents")


# --- corroboration ----------------------------------------------------------
# Write-once-then-upgrade: an existing `by` survives an agent call (the agent channel can
# only downgrade, never delete a human/scanner attestation) but a human/scanner value
# replaces an agent one (consult 007 / ADR-008).
Q_CORROBORATE = """
MATCH (m:Node {id:$m}), (s:Node {id:$s})
WHERE m:Memory AND s:Source
MERGE (m)-[r:CORROBORATED_BY]->(s)
SET r.by = CASE WHEN r.by IS NULL THEN $by
                WHEN $by IN ['human','scanner'] THEN $by
                ELSE r.by END
RETURN m.id, s.id
"""

# --- sessions / agents ------------------------------------------------------
Q_GET_SESSION = "MATCH (se:Node {id:$id}) WHERE se:Session RETURN se.id LIMIT 1"
Q_CREATE_SESSION = """
CREATE (se:Node:Session) SET se.id = $id, se.tenant = $tenant, se.runtime = $runtime,
    se.agent_id = $agent, se.status = 'ok', se.started_at = $now, se.created_at = $now
RETURN se.id
"""
Q_SESSION_READ = """
MATCH (se:Node {id:$sess}), (n:Node {id:$n})
WHERE se:Session
MERGE (se)-[r:READ]->(n) SET r.at = $now
RETURN n.id
"""
# last K distinct read targets of a session (conservative influence window)
Q_READ_WINDOW = """
MATCH (se:Node {id:$sess})-[r:READ]->(n:Node)
WHERE se:Session
WITH n, max(r.at) AS at ORDER BY at DESC LIMIT $k
RETURN n.id, n.status
"""
Q_SESSION_INFO = "MATCH (se:Node {id:$sess}) WHERE se:Session RETURN se.runtime, se.agent_id LIMIT 1"

# --- traversal --------------------------------------------------------------
# algo.BFS follows only outgoing edges of ONE type; FEEDS is the mirror of DERIVED_FROM.
Q_DESCENDANTS = """
MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'FEEDS') YIELD nodes
UNWIND nodes AS n RETURN n.id, n.status
"""
Q_ANCESTORS = """
MATCH (r:Node {id:$id}) CALL algo.BFS(r, $depth, 'DERIVED_FROM') YIELD nodes
UNWIND nodes AS n RETURN n.id, n.status
"""
Q_ANCESTOR_EDGES = """
UNWIND $ids AS i
MATCH (c:Node {id:i})-[d:DERIVED_FROM]->(p:Node)
RETURN c.id, p.id, coalesce(d.rel, 'derive'), d.via
"""
Q_TAINT_PARENT = "MATCH (n:Node {id:$id}) RETURN n.taint_parent"
Q_NODE_DETAILS = """
UNWIND $ids AS i
MATCH (n:Node {id:i})
RETURN n.id, labels(n), n.status, coalesce(n.low_integrity, false), n.taint_parent, n.kind
"""

# --- revoke -----------------------------------------------------------------
# CAS barrier: flips only if not already revoked; creates the Revocation row in the
# SAME query (WITH chains so the CREATE runs only when the MATCH produced a row).
Q_REVOKE_ROOT = """
MATCH (r:Node) WHERE r.id = $id AND r.status <> 'revoked'
  AND ('Source' IN labels(r) OR 'Memory' IN labels(r))
SET r.status = 'revoked', r.revoked_at = $now, r.reason = $why, r.taint_parent = NULL
WITH r CREATE (v:Node:Revocation {id:$rid, tenant:$tenant, root_id:$id, reason:$why,
    kind:$kind, state:'running', started_at:$now, created_at:$now})
RETURN r.id
"""
Q_REVOKED_ROOTS = "MATCH (r:Node {status:'revoked'}) RETURN r.id, r.tenant"
Q_QUARANTINE_CHUNK = """
UNWIND $ids AS i MATCH (n:Node {id:i}) WHERE n.status IN ['ok','preserved']
SET n.status = 'quarantined' RETURN count(n) AS n
"""
Q_WRITE_FINAL = """
UNWIND $b AS b MATCH (n:Node {id:b[0]}) WHERE n.status <> 'revoked'
SET n.status = b[1][0], n.taint_parent = b[1][1] RETURN count(n) AS n
"""
Q_PARENTS_OF = """
UNWIND $ids AS i MATCH (c:Node {id:i})-[:DERIVED_FROM]->(p:Node) RETURN c.id, p.id
"""
Q_SUPPORT_OF = """
UNWIND $ids AS i MATCH (m:Node {id:i})-[:CORROBORATED_BY]->(s:Source)
WHERE m:Memory
RETURN m.id, s.id, s.status
"""
Q_ACTION_DETAILS = """
UNWIND $ids AS i MATCH (a:Node {id:i}) WHERE a:Action
RETURN a.id, a.tool, a.summary, a.effect, a.risk, coalesce(a.artifacts, []), a.status
"""
Q_MEMORY_ARTIFACTS = """
UNWIND $ids AS i MATCH (m:Node {id:i}) WHERE m:Memory AND m.artifact IS NOT NULL
RETURN m.id, m.artifact, m.status
"""
Q_REVOCATION_LATEST = """
MATCH (v:Revocation {root_id:$id}) WHERE v.state IN ['running','done'] AND v.kind IN ['revoke','supersede']
RETURN v.id, v.state, v.started_at ORDER BY v.started_at DESC LIMIT 1
"""
Q_REVOCATION_SET_STATE = """
MATCH (v:Node {id:$rid}) WHERE v:Revocation
SET v.state = $state, v.finished_at = $now,
    v.n_tainted = $t, v.n_preserved = $p, v.n_actions = $a
RETURN v.id
"""
Q_RUNNING_REVOCATIONS = """
MATCH (v:Revocation {state:'running'}) RETURN v.id, v.root_id, v.tenant ORDER BY v.started_at
"""
Q_QUARANTINED_NODES = "MATCH (n:Node {status:'quarantined'}) RETURN n.id, coalesce(n.tenant, '') AS tenant"
Q_REINSTATE_ROOT = """
MATCH (r:Node) WHERE r.id = $id AND r.status = 'revoked'
  AND ('Source' IN labels(r) OR 'Memory' IN labels(r))
SET r.status = 'ok', r.revoked_at = NULL, r.reason = NULL, r.taint_parent = NULL
WITH r CREATE (v:Node:Revocation {id:$rid, tenant:$tenant, root_id:$id, reason:$why,
    kind:'reinstate', state:'running', started_at:$now, created_at:$now})
RETURN r.id
"""
Q_REVOCATION_SUPERSEDE = """
MATCH (v:Node) WHERE v:Revocation AND v.root_id = $id AND v.state = 'running' AND v.kind <> 'reinstate'
SET v.state = 'superseded', v.finished_at = $now
RETURN v.id
"""

# --- what-if / checkpoint ---------------------------------------------------
Q_COPY = None  # GRAPH.COPY is issued via the client's copy() helper, not as Cypher text

# --- audit ------------------------------------------------------------------
Q_PAGERANK_SOURCES = """
CALL algo.pageRank('Node','DERIVED_FROM') YIELD node, score
WHERE 'Source' IN labels(node) AND node.status = 'ok'
RETURN node.id, node.kind, score ORDER BY score DESC, node.id LIMIT $k
"""
Q_AUDIT_UNRANKED_SOURCES = """
MATCH (s:Source {status:'ok'}) WHERE NOT s.id IN $ranked
RETURN s.id, s.kind ORDER BY s.id LIMIT $k
"""
#: exact reach count for many roots at once (paired with the PageRank ranking above)
Q_DESCENDANT_COUNTS = """
UNWIND $ids AS i MATCH (r:Node {id:i}) CALL algo.BFS(r, -1, 'FEEDS') YIELD nodes
RETURN r.id AS id, size(nodes) AS n
"""

# --- invariants (aggregate counts; see db/schema.py) ------------------------
Q_INV_COUNT_NODES = "MATCH (n) RETURN count(n) AS n"
Q_INV_NOT_NODE = "MATCH (n) WHERE NOT n:Node AND NOT n:CaptureReceipt RETURN count(n) AS n"
Q_INV_BAD_TYPE = """
MATCH (n) WHERE NOT (n:Source OR n:Memory OR n:Action OR n:Session OR n:Agent OR n:Revocation OR n:CaptureReceipt)
RETURN count(n) AS n
"""
Q_INV_MULTI_TYPE = """
MATCH (n) WHERE (CASE WHEN n:Source THEN 1 ELSE 0 END
    + CASE WHEN n:Memory THEN 1 ELSE 0 END
    + CASE WHEN n:Action THEN 1 ELSE 0 END
    + CASE WHEN n:Session THEN 1 ELSE 0 END
    + CASE WHEN n:Agent THEN 1 ELSE 0 END
    + CASE WHEN n:Revocation THEN 1 ELSE 0 END) > 1
RETURN count(n) AS n
"""
Q_INV_BAD_STATUS = "MATCH (n) WHERE NOT n.status IN $allowed RETURN count(n) AS n"
# Every :Node entity carries a status property except :Revocation, whose lifecycle property
# is `state` (running|done) - QA finding 2026-10-15: `NOT n.status IN [...]` is NULL for a
# missing property, so absence was invisible. See docs/KNOWN_ISSUES.md.
Q_INV_MISSING_STATUS = """
MATCH (n:Node) WHERE n.status IS NULL AND NOT n:Revocation
RETURN count(n) AS n
"""
Q_INV_NO_ID = "MATCH (n) WHERE n.id IS NULL RETURN count(n) AS n"
Q_INV_MISSING_FEEDS = """
MATCH (c:Node)-[:DERIVED_FROM]->(p:Node)
OPTIONAL MATCH (p)-[f:FEEDS]->(c)
WITH c, p, f WHERE f IS NULL RETURN count(*) AS n
"""
Q_INV_MISSING_DERIVED = """
MATCH (p:Node)-[:FEEDS]->(c:Node)
OPTIONAL MATCH (c)-[d:DERIVED_FROM]->(p)
WITH c, p, d WHERE d IS NULL RETURN count(*) AS n
"""
Q_INV_TAINTED_NO_PARENT = "MATCH (n:Node {status:'tainted'}) WHERE n.taint_parent IS NULL RETURN count(n) AS n"
Q_INV_TAINTED_PARENT_MISSING = """
MATCH (n:Node {status:'tainted'})
OPTIONAL MATCH (p:Node {id:n.taint_parent})
WITH n, p WHERE p IS NULL RETURN count(n) AS n
"""
Q_INV_TAINTED_PARENT_HEALTHY = """
MATCH (n:Node {status:'tainted'}) MATCH (p:Node {id:n.taint_parent})
WHERE NOT p.status IN ['tainted','revoked','quarantined'] RETURN count(n) AS n
"""
Q_INV_PRESERVED_NO_SUPPORT = """
MATCH (n:Memory {status:'preserved'})
OPTIONAL MATCH (n)-[:CORROBORATED_BY]->(s:Source)
WITH n, count(s) AS c WHERE c = 0 RETURN count(n) AS n
"""
Q_INV_PRESERVED_WEAK_SUPPORT = """
MATCH (n:Memory {status:'preserved'})
OPTIONAL MATCH (n)-[:CORROBORATED_BY]->(s:Source)
WITH n, sum(CASE WHEN s.status = 'ok' THEN 1 ELSE 0 END) AS healthy
WHERE healthy = 0 RETURN count(n) AS n
"""
Q_INV_BAD_TENANT = "MATCH (n) WHERE coalesce(n.tenant, '') <> $tenant RETURN count(n) AS n"
Q_INV_REVOKED_SHAPE = """
MATCH (n:Node {status:'revoked'})
WHERE NOT ('Source' IN labels(n) OR 'Memory' IN labels(n)) OR n.revoked_at IS NULL
RETURN count(n) AS n
"""
Q_INV_REVOKED_ORPHAN = "MATCH (n:Node) WHERE n.revoked_at IS NOT NULL AND n.status <> 'revoked' RETURN count(n) AS n"
Q_INV_EDGES = "MATCH (a:Node)-[:DERIVED_FROM]->(b:Node) RETURN a.id, b.id"

# --- reports ----------------------------------------------------------------
Q_STATUS_COUNTS = "MATCH (n:Node) RETURN n.status AS status, count(*) AS n"
Q_REVOCATION_COUNTS = "MATCH (v:Revocation) RETURN v.state AS state, count(*) AS n"

# --- registry (F-05) ---------------------------------------------------------
Q_REGISTRY_UPSERT = "CREATE (t:Tenant {id:$id, status:'active', node_cap:$cap, agent_token_sha256:$agent_sha, operator_token_sha256:$operator_sha, created_at:$now})"
Q_REGISTRY_BY_ID = "MATCH (t:Tenant {id:$id}) RETURN t.id, t.status, t.node_cap, t.created_at, t.token_sha256, t.agent_token_sha256, t.operator_token_sha256"
Q_REGISTRY_BY_DIGEST = """
MATCH (t:Tenant)
WHERE t.agent_token_sha256=$sha OR t.operator_token_sha256=$sha OR t.token_sha256=$sha
RETURN t.id,t.status,t.node_cap,t.created_at,t.token_sha256,t.agent_token_sha256,t.operator_token_sha256
LIMIT 2
"""
Q_REGISTRY_ALL = "MATCH (t:Tenant) RETURN t.id, t.status, t.node_cap, t.created_at"
Q_REGISTRY_SET_STATUS = "MATCH (t:Tenant {id:$id}) SET t.status = $status"
Q_REGISTRY_ISSUE_OPERATOR = "MATCH (t:Tenant {id:$id}) SET t.credential_epoch = coalesce(t.credential_epoch,0) + 1 WITH t WHERE t.status = 'active' AND ($rotate OR t.operator_token_sha256 IS NULL) SET t.operator_token_sha256 = $sha RETURN t.id"

# --- gate (F-11) -------------------------------------------------------------
Q_GATE_NODES = """
UNWIND $ids AS i MATCH (n:Node {id:i})
RETURN n.id, n.status, coalesce(n.low_integrity, false), coalesce(n.conf_eff, []), n.taint_parent
"""
# Demo preflight reads immutable identity without changing existing lifecycle state.
Q_DEMO_IDENTITIES = """
UNWIND $ids AS i MATCH (n:Node {id:i}) RETURN n.id, labels(n), properties(n)
"""
Q_DEMO_ADD_SUPPORT = """
MATCH (m:Node {id:$memory_id}), (s:Node {id:$source_id})
WHERE m:Memory AND s:Source
MERGE (m)-[c:CORROBORATED_BY]->(s) ON CREATE SET c.by = $by
RETURN m.id
"""
Q_UI_NODES = """
MATCH (n:Node) WHERE n:Source OR n:Memory OR n:Action
RETURN n.id, labels(n), n.status, n.kind, n.title, n.uri, n.tool, coalesce(n.low_integrity,false)
ORDER BY n.created_at, n.id LIMIT $limit
"""
Q_UI_EDGES = """
UNWIND $ids AS id MATCH (a:Node {id:id})-[r:DERIVED_FROM|CORROBORATED_BY]->(b:Node)
WHERE b.id IN $ids RETURN a.id, b.id, type(r) ORDER BY a.id, b.id LIMIT $limit
"""
Q_GATE_SUPPORT = """
UNWIND $ids AS i MATCH (n:Node {id:i})-[c:CORROBORATED_BY]->(s:Source)
WHERE n:Memory
RETURN n.id, s.id, s.status, c.by
"""
Q_INV_OK_HAS_NO_BAD_PARENT = """
MATCH (n:Node {status:'ok'})-[:DERIVED_FROM]->(p:Node)
WHERE p.status IN ['revoked','tainted','quarantined'] RETURN count(n)
"""

# Weak connectivity of lineage, excluding session/history/receipt metadata.
Q_WCC_SUMMARY = """
CALL algo.WCC({nodeLabels:['Node'], relationshipTypes:['DERIVED_FROM','CORROBORATED_BY']})
YIELD node, componentId
WHERE node:Source OR node:Memory OR node:Action
RETURN componentId, count(node) AS size
ORDER BY size DESC, componentId ASC LIMIT $limit
"""
