# F-01 - Repo skeleton, config, FalkorDB lifecycle, schema

Status: qa | Tests: `tests/unit/test_config.py`, `tests/integration/test_schema.py` | QA: pending `docs/qa/F-01.md`

## Behaviour
- `pedigree.config.Settings` (pydantic-settings): fails LOUDLY (no silent defaults) on a bad
  `PEDIGREE_*` env; `get_settings()` is cached; `.env` is read if present.
- `graph_name(tenant) == f"ped:{tenant}"` is the single choke point from tenant id to graph name.
- `validate_id`: `^[A-Za-z0-9._:/@#_-]{1,128}$` (ADR-004); empty/oversize/space/quote rejected.
- `pedigree db start|stop|status` (via `make start-db` etc.): Docker path pinned to
  `falkordb/falkordb:v4.22.1` (ADR-001) with mandatory module args
  `TIMEOUT_MAX 60000 TIMEOUT_DEFAULT 20000 QUERY_MEM_CAPACITY 1073741824`; idempotent when
  already running; waits for ping; `db status` prints `graph module ver 42201` and exits
  non-zero on any other version.
- `db/schema.ensure_schema(db, gname)`: idempotent; creates 5 property indexes (Node.id,
  Memory.artifact_key, Action.artifact_key, Revocation.root_id, Revocation.state), waits for
  OPERATIONAL (`CALL db.indexes()` polling - GOTCHAS #4), then a UNIQUE constraint on
  `Node(id)` via `GRAPH.CONSTRAINT` (never dropped; GOTCHAS #2).
- `check_invariants(db, gname, expected_tenant)`: read-only oracle returning a list of
  human-readable violations (empty = healthy); never raises; 13 checks listed in schema.py.

## Data model / Cypher touched
- All DDL is static; constraint creation is a raw admin command (idempotent, "already exists" benign).
- Indexes: `db/queries.py::Q_INDEX_*`, wait+count: `Q_INDEXES`.

## Invariants
- Two `ensure_schema` calls in a row leave the same index set, all OPERATIONAL.
- Duplicate `Node(id)` insert is refused by the DB (server message:
  `unique constraint violation on node of type Node`; mapped to typed `Conflict`).

## Acceptance tests (AT0.1, AT0.3, AT0.4, AT0.5)
- `tests/unit/test_config.py`: graph_name, tenant validation cases (ab, ABC, a_b, abc:x, 25 chars, empty).
- `tests/integration/test_schema.py::test_ensure_schema_is_idempotent` (property coverage, not
  row count: FalkorDB merges per-label property indexes into one row).
- `tests/integration/test_schema.py::test_unique_constraint_rejects_duplicate_ids`.
- `tests/integration/test_schema.py::test_invariants_*` (healthy, unknown status, broken
  mirror, cycle, wrong tenant).
- `scripts/clean_clone_check.sh` (AT0.6): fresh clone -> venv -> lint -> tests -> scans.

## Security notes
- No tenant data ever reaches Cypher by interpolation; `graph_name` is the only name builder.
- `secret_scan.py` in `make check`; `.gitignore` excludes `.env`, `bin/`, `data/`, `.venv/`.

## Evidence needed
- `make db-status` output showing `ver 42201`; pytest integration output; clean-clone log.
