# Empty durable production launch

Acceptance criteria:

- Default Compose requires generated admin, database, application and tenant ACL secrets.
- First boot creates no tenant, synthetic node or shared login credential.
- Production refuses demo seed/login settings before any seeding can run.
- Authenticated API-created data survives API and database container restarts.
- FalkorDB writes AOF on its named persistent volume and requires authentication.
- Render declares a database disk, database authentication and an always-on API.
- Explicit local demo configuration remains available separately for regression scenarios.
- Configuration representations never disclose credential fields.

No API contract is changed. Configuration acceptance checks are in
`tests/unit/test_production_launch.py`; runtime evidence must be recorded separately.
