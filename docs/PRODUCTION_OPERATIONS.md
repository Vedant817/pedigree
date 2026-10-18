# Production operations

Default Compose starts an empty service and persistent authenticated FalkorDB. It
never seeds scenarios or enables the local demo login. The synthetic walkthrough is
an optional, separate `docker-compose.demo.yml` configuration.

## Configure and start

Create an ignored `.env` containing separate cryptographically generated values for
`PEDIGREE_ADMIN_TOKEN`, `PEDIGREE_SECRET`, `PEDIGREE_DB_ACL_SECRET` and
`FALKOR_PASSWORD`. Generate each with Python's `secrets.token_urlsafe`; keep them
private. Do not reuse tenant bearer credentials as database or deployment secrets.

```sh
docker compose up --build --wait
```

The service binds loopback by default. Put a trusted TLS proxy in front of it for
remote access. The database has no published host port. Provision your tenant with
`POST /admin/tenants`, a JSON `id`, and the `x-admin-token` deployment header.
Store the returned agent/operator credentials privately. Agent tools receive only
the agent credential. The browser's operator credential permits lifecycle changes.
Credentials are generated per tenant; no tenant identity is taken from request bodies
on the tenant API.

Capture your repository through the adapters, REST or MCP. An empty graph is expected
until actual work is captured. Unknown IDs are not evidence of safety.

## Persistence and recovery

Keep the named database volume. `docker compose down` preserves named volumes; deleting
them discards data. AOF uses periodic fsync, so ordinary operations can lose the most
recent interval on a host failure. Application-consistent recovery requires a tested
checkpoint/backup procedure and an off-host backup; a single disk is not redundancy.
Never repair a crashed production database by deleting or reseeding its volume.

## Render

`render.yaml` declares the existing separate API/database services, a persistent graph
disk, database authentication and an always-on API. This entails paid resources.
Synchronizing a Blueprint is a deployment operation, not a local check. Verify account
credits and cost in Render before applying it. Attaching a disk to an existing service
needs a planned data migration: its former ephemeral files do not become a verified
backup automatically. Confirm mounted paths, restart survival and restore before
accepting real user data.

The current user's release session leaves Render billing and live resource changes
to the user. Source declarations do not establish hosted persistence or test results.
