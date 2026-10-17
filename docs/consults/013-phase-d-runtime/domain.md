# Domain review: choose A

Use a non-root `python:3.12-slim` API and separate pinned FalkorDB service.
Keep DB unpublished; bind the judge API to loopback. Separate processes give
Compose real dependency health and shutdown ordering. `service_healthy` waits for
healthchecks, while ordinary dependency startup does not establish readiness
([Docker](https://docs.docker.com/compose/how-tos/startup-order/)). Validate the
actual module version and limits, not PING alone. Use exec-form API launch;
fail startup if requested demo seeding fails instead of silently serving an empty demo.

## Observed commands, 2026-10-17

All commands were read-only against existing `pedigree-db`; no data was created,
deleted, or enumerated:

```text
docker inspect pedigree-db --format '{{.Config.Image}} {{.HostConfig.RestartPolicy.Name}}'
=> falkordb/falkordb:v4.22.1 no
docker exec pedigree-db redis-cli PING
=> PONG
docker exec pedigree-db redis-cli MODULE LIST
=> graph ver 42201; vectorset ver 1
docker exec pedigree-db redis-cli GRAPH.CONFIG GET TIMEOUT_MAX
=> 60000
docker exec pedigree-db redis-cli GRAPH.CONFIG GET TIMEOUT_DEFAULT
=> 20000
docker exec pedigree-db redis-cli GRAPH.CONFIG GET QUERY_MEM_CAPACITY
=> 1073741824
docker exec pedigree-db redis-cli CONFIG GET appendonly
=> yes
docker exec pedigree-db redis-cli CONFIG GET save
=> 900 1
docker exec pedigree-db redis-cli GRAPH.RO_QUERY pedigree:registry "RETURN 1" --compact
=> scalar 1; internal execution 0.608323 milliseconds
```

## Compatibility and risks

Official [0.10.0 metadata](https://pypi.org/pypi/falkordblite/0.10.0/json),
read using Python urllib/json without installation, reports Python `>=3.12.0`,
Linux CPython312 wheels `manylinux_2_39_{x86_64,aarch64}` and macOS wheels.
Do not promise arbitrary Linux wheel compatibility. Its
[published interface](https://pypi.org/project/falkordblite/0.10.0/) imports
`redislite`, and macOS needs libomp; current script instead probes
`import falkordblite`. Keep the no-Docker acceptance target explicit: tested
Linux architecture/distribution plus verified external 4.22.1 module. macOS
wheel availability does not prove pinned-module equivalence or native acceptance.
The [Python image documentation](https://hub.docker.com/_/python) warns slim lacks
extension build tools; verify the locked install on Linux.

Preserve demo credentials across restarts in a private owner-writable mounted
directory, never logs. POSIX0600 does not establish Windows ACL privacy.
Missing credentials for an existing tenant must require explicit recovery, never
silent rotation. Test repeated seed identity/count stability, read-only credential
directory failure, wrong DB module rejection, fresh-volume boot, and SIGTERM
shutdown/restart persistence on an isolated project. Confidence: high for observed
DB settings and metadata; runtime topology, clean Linux installation and macOS
remain proposed until exercised.
