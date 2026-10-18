# Tenant database ACL enforcement

Decision, 2026-10-18: tenant operations receive a distinct `Db` authenticated as
`t_<tenant>` after bearer resolution. Registry and ACL provisioning retain the
deployment connection. REST handlers, MCP tools and startup reconciliation all
select the same tenant factory. Engine contracts and graph names are unchanged.

ACL passwords are HMAC-derived from `PEDIGREE_DB_ACL_SECRET`, independently from
bearer tokens. Production ACL mode requires an explicit secret of at least 32
characters. Development/test/local use a process-local cryptographic secret when
none is configured. Deployments sharing a database must configure the same secret;
rotating it requires restarting all service processes. Provisioning is repeated at
admission to recover ACL state after database restart. Failures are returned and
never retry tenant work as administrator.

The tenant identity permits exact main graph, what-if and checkpoint graph families,
and only that tenant's quota mutex. Redis key permissions protect both copy source
and destination. `GRAPH.LIST` and ACL management are withheld. What-if maintenance
uses privileged enumeration internally and filters graph names against validated
tenant namespaces before exposing them to the engine. The scoped `Db` rejects
invalid graph family names before issuing graph operations.

`PEDIGREE_DB_ACL=false` explicitly retains prior API-only isolation for deployments
without ACL support. This mode must not be advertised as database isolation.
Production must use authenticated, private DB networking and durable storage;
neither is provided by this connection change. Tenant database users are an
application containment boundary, not credentials delivered to end users.

Evidence: `tests/security/test_tenant_db_service.py`; consult 014. Hosted preview
and TestSprite acceptance are separate and have not been established by local tests.
