# F-02 - Ingest engine (record_source / remember / record_action / corroborate)

Status: qa | Tests: `tests/integration/test_core_scenario.py` | QA: pending `docs/qa/F-02.md`

## Behaviour
- `record_source(db, gname, tenant, kind, uri=, title=, integrity=, conf=, id=)`: creates a
  `:Node:Source` with `status='ok'`; default integrity from `config.default_integrity(kind)`
  (web/agent = untrusted -> `low_integrity=true`); returns warnings (`untrusted_source`).
- `remember(...)`: creates `:Node:Memory` with parents (`derived_from`) and support
  (`corroborated_by`) in ONE atomic query per case:
  - parents given -> `q_create_with_parents('Memory')`: creates the node, the DERIVED_FROM
    edges and the mirrored FEEDS edges, and inherits status:
    `quarantined` if any parent is revoked/tainted/quarantined, else `ok`;
    `low_integrity`/`conf_eff` unioned from parents + own tags.
  - no parents -> `q_create_orphan('Memory')` with `unanchored=true`, `low_integrity=true`,
    warning `unanchored` (an unsupported belief is never silently trusted).
- Missing parents are detected BEFORE the write (`require_nodes` -> typed `NotFoundInGraph`,
  GOTCHAS #16: `MATCH` would silently drop them). After the write, if fewer parents were
  linked than requested, the call raises `Conflict` (no partial edge set is kept).
- `record_action(...)`: `:Node:Action` (`tool`, `summary`, `effect` in
  reversible|irreversible|unknown, `risk`, `artifacts` validated as printable 1..512 chars),
  relies on memories via `rel:'rely'`; born-quarantined rule identical.
- `corroborate(memory, source, by in agent|human|scanner)`: CORROBORATED_BY edge; both nodes
  must exist, else `NotFoundInGraph`.
- Sessions: `ensure_session`, `session_read` (SESSION_READ edge + recorded in read window),
  `read_window`, `artifact_lookup` (path@sha256 on Memory first, then Action).

## Data model / Cypher touched
- Queries: `Q_CREATE_SOURCE`, `q_create_with_parents(label)`, `q_create_orphan(label)`,
  `Q_CORROBORATE`, `Q_CREATE_SESSION`, `Q_SESSION_READ`, `Q_READ_WINDOW`,
  `Q_ARTIFACT_LOOKUP_*`, `Q_FIND_IDS`. The only `.format` in the codebase lives in
  `q_create_with_parents`, fed by the `_label()` allow-list (`Node`, `Source`, `Memory`,
  `Action`, `Revocation`).

## Invariants
- DERIVED_FROM <-> FEEDS mirrored 1:1 (checked by `check_invariants`).
- Every node has exactly one type label from the allowed set and a status in
  ok|tainted|preserved|quarantined|revoked.
- Untrusted ancestry => the child is `low_integrity`.

## Acceptance tests (AT0.2)
- `test_core_scenario.py::_build` + status expectations after revoke (5 tainted / 1 preserved).
- `test_child_of_tainted_parent_is_born_quarantined`.
- `test_artifact_key_cross_session_link`.
- `test_ingest_and_revoke_errors` (missing parent, bad kind, oversize text, duplicate id).
- `verify` unit coverage: `tests/unit/test_config.py` (id/artifact validation).

## Security notes
- Tenant comes from the caller (later: token only); text stored only if
  `PEDIGREE_STORE_TEXT=true`, else hash-only (privacy default).
- Array caps (`derived_from` 64, `corroborated_by` 64, `artifacts` 32, conf tags 16x32 chars)
  and text/uri/title length caps from `config.LIMITS`.

## Evidence needed
- pytest output; a QA-authored independent probe re-deriving counts/statuses.
