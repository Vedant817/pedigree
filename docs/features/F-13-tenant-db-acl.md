# F-13: enforce tenant database credentials in the service

Acceptance: REST, MCP and startup recovery select a database authenticated as the
resolved tenant. Registry/provisioning retain administrative credentials. Tenant
clients cannot query/copy foreign graphs, registry graphs or foreign quota keys,
and cannot enumerate graphs or administer ACLs. Main graph, validated what-if and
checkpoint descendants and the exact tenant quota mutex are allowed. Provisioning
or authentication failures must not retry using administrative credentials.

Compatibility: `PEDIGREE_DB_ACL=false` explicitly retains API-only isolation.
Development can use a process-local secret; production ACL mode requires an
explicit deployment secret. Passwords are derived separately for each tenant.
What-if cleanup may use administrator enumeration internally but exposes only
validated graph names in that tenant namespace. No public API shapes change.

Checks: `tests/security/test_tenant_db_service.py`: real REST/MCP writes, raw ACL
denials, quota/what-if lifecycle, reprovisioning, provisioning failure injection,
namespace properties and disabled-mode behavior. Existing integration suites are
regression checks. TestSprite/hosted verification remain separate release gates.
