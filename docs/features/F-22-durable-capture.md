# F-22 durable capture

Accept sanitized Claude hook capture to a private, bounded SQLite outbox before
network access. Bind each outbox to exact endpoint and credential fingerprint.
Replay immutable envelopes in order under an interprocess lock. Do not queue gates.
When capture cannot drain before a gate, deny with recovery guidance.

Optional REST delivery_id provides replay identity. A tenant graph metadata receipt
binds the immutable payload digest, resolved artifact aliases, cursor and result.
Action nodes carry an atomic receipt fingerprint on creation. A retry after a
partial create repairs session edges, without recreating actions. Metadata counts
against tenant quota. Existing callers retain sequential event behavior.

Acceptance: offline capture/restart, lost acknowledgement, partial commits, changed
payload rejection, storage bounds/corruption, endpoint/credential switching,
concurrent drain, no cached gate approval; real FalkorDB graph invariants pass.
Installed Claude runtime acceptance and hosted PR testing are separate gates.

Builder verification on fresh FalkorDB v4.22.1, isolated port 6383:

- Initial test-first spool unit test failed because Spool was absent.
- `make check PY=../pedigree/.venv/Scripts/python.exe` with `PYTHONPATH=src`,
  `FALKOR_PORT=6383`: 886 passed, 1 skipped, 6 deselected, 1 xfailed in 246.70s;
  ruff, tracked-file secret scan, number check and README check passed (exit 0).
- Focused hook/spool/real-DB delivery suite: 41 passed in 18.94s.
- Updated bounded-backlog/interprocess test suite: 6 passed in 4.04s; ruff passed.
- Real stdlib hook subprocess captured offline, denied a pending gate, delivered to
  a spawned HTTP service, then retained one action/source across service restart.
- First broad run had one existing MCP stdio response-race failure; focused rerun
  and the complete second run passed. No assertion was weakened.

Receipt index/schema and invariants are exercised on the real DB. Fixture teardown
tracks exact created tenants; two initial failed-test empty registry fixtures were
removed by their exact retained IDs and verified absent. No other DB was mutated.
This is builder evidence; independent QA/red-team, installed Claude execution and
hosted preview/TestSprite evidence remain open.
