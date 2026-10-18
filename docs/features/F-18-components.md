# Weakly connected lineage components

`GET /v1/audit/components?limit=50` returns component identifiers and node counts,
ordered by descending size. It uses authenticated tenant-derived DB access, rate
admission, the standard read timeout, and a static parameterized `algo.WCC` query.
Connectivity uses `DERIVED_FROM` and `CORROBORATED_BY`, ignoring edge direction.
Only Source, Memory and Action nodes count; sessions, receipts and history do not.
Component identifiers belong to a particular snapshot and must not be persisted as
stable identities. The bounded summary reports truncation explicitly.

The procedure contract was already observed in
`docs/tech/examples/py/04_algorithms.py`. Acceptance covers isolated nodes, separate
chains, reversed edges/cycles, explicit truncation, empty graphs and query failures
on real FalkorDB. REST authorization/isolation is verified after ACL integration.
