# P-003 red-team: credential, admin and network boundaries

Status: complete. Owner: independent red-team session (no product code or test edits,
no fixes). Probes live under `scratch/qa-redteam-p003/` (gitignored); this file is the
deliverable. Nothing was committed.

Verdict: **PASS for the authorized boundaries, with two low-severity issues.**
Credential-material isolation, demo-mode deployment-admin denial, loopback-only host
publication, proxy-header distrust and fail-closed seeding all held under adversarial
probing. No High/Critical finding; no boundary bypass reproduced. Two genuine
low-severity deviations were found (F1: unauthenticated MCP health / tool inventory;
F2: the demo-disabled admin route parses the body before denying), plus four
informational observations. Details below.

## Environment and method

- Commit under test: `4d9c50729cca86213aa5f26900b45b1dfd4349aa` (HEAD of the main repo at
  test time). The intended commit `1c1ce2a` **is an ancestor** of HEAD:
  `git merge-base --is-ancestor 1c1ce2a HEAD` → exit `0`.
- Delta `1c1ce2a..HEAD` touches two files in this attack surface (reviewed, and the
  resulting image was the one tested):
  - `scripts/entrypoint.sh`: uvicorn port is now `"${PORT:-8000}"` (was literal `8000`);
    `--no-proxy-headers` retained.
  - `Dockerfile`: healthcheck now reads `PORT`/`8000`.
  - No change to the bind address (still `--host 0.0.0.0` inside the container network
    namespace) and no change to the compose host mapping (still `127.0.0.1:...`), so the
    network posture claimed by P-003/P-004 is unchanged by the delta.
- Date/time: 2026-10-17, ~14:46–14:56 local.
- Host: Windows (win32), Docker Engine `29.8.2`, Docker Compose `v5.5.1`,
  image runtime Python `3.12.15`, uvicorn `0.54.0`, FalkorDB `falkordb/falkordb:v4.22.1`.
- Isolated project: `pedigree-rt003`, clone at `%TEMP%\rt003-clone`, host port `8012`
  (`$env:PEDIGREE_PORT='8012'`). Unrelated stacks (`pedigree-pedigree-1` on 8000,
  `pedigree-db` on 6379) were left alone.
- `docker compose -p pedigree-rt003 up -d --build --wait` → exit `0`; both containers
  healthy. Shell variables used below:
  `$S = C:\Users\vedan\Documents\Resources\Code\pedigree\scratch\qa-redteam-p003`,
  `$U = http://127.0.0.1:8012`. Compose commands were run from the clone with
  `$env:PEDIGREE_PORT='8012'`.
- Credential handling rule observed throughout: the token value is never printed or
  written outside the single copied credential file; scans report counts only.

```text
$ docker compose -p pedigree-rt003 ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'
NAME                        STATUS                    PORTS
pedigree-rt003-db-1         Up (healthy)              6379/tcp
pedigree-rt003-pedigree-1   Up (healthy)              127.0.0.1:8012->8000/tcp
```

## Attack inventory (attacks tried, with result)

| # | Attack | Result |
|---|---|---|
| 1 | Find the demo credential in git, build context, image layers, container `/data` | Not tracked; not in context; not in image (empty `/data/credentials`) |
| 2 | Scan container env, compose logs, `docker inspect` for exact token values and token-shaped strings | 0 matches everywhere |
| 3 | `GET`/`POST /admin/tenants` with no / arbitrary / token-shaped header | 403 |
| 4 | `POST /admin/tenants` malformed JSON, oversized declared body, chunked 300 KB, duplicate `Content-Length` | 422 / 413 / 413 / 400 (F2 on the 422) |
| 5 | `GET /metrics`, `/docs`, `/openapi.json`, `/redoc` unauthenticated | 403 / 404 / 404 / 404 |
| 6 | `POST /v1/admin/resume` unauthenticated / token-shaped header | 403 / 403 |
| 7 | Host publication of the DB port; API reachable on LAN/WSL/Tailscale addresses; DB container IP from host | Unpublished; refused; unreachable |
| 8 | Forged `X-Forwarded-For` / `X-Real-IP` / `Forwarded` with valid, invalid and absent credentials | Status unchanged; logged peer is the real Docker peer |
| 9 | Boot with the credential file deleted | Exit 1, actionable credential-free message, API never comes up |
| 10 | Boot with the tenant revoked in the registry graph | Exit 1, actionable credential-free message |
| 11 | MCP `initialize`, `tools/list`, `pedigree_health` with no credential; bogus bearer | Allowed (F1); write tool refused |
| 12 | Operator-token rotation: old token after rotation | 401 (refused); new token 200; agent token unaffected |
| 13 | Demo-mode CLI `admin create-tenant` with no `PEDIGREE_ADMIN_TOKEN` | Succeeds (F3, same-trust-domain observation) |
| 14 | Static path traversal `/../scripts/seed_demo.py`, `..%2f`, `/data/credentials/...` | 404, no content |
| 15 | Volume ownership/perms, `compose ls`/`config`/`inspect`, healthcheck command inspection | No secret exposure (F5 tooling quirk only) |

## Case 1 — Credential material

```powershell
$tracked = git -C "$env:TEMP\rt003-clone" ls-files | Select-String -Pattern "demo-demo"
"tracked_matches=$(@($tracked).Count)"           # -> 0
Get-Content "$env:TEMP\rt003-clone\.dockerignore" # excludes .env*, scratch/, data/
docker run --rm --entrypoint bash pedigree:local -c "ls -laR /data; find / -xdev -name 'demo-*.json' -print 2>/dev/null"
docker compose -p pedigree-rt003 exec -T pedigree sh -c "id; ls -la /data; ls -la /data/credentials; stat -c '%a %u:%g %n' /data/credentials/demo-demo.json"
docker compose -p pedigree-rt003 exec -T pedigree sh -c "env"   > "$S\case1-env.txt"
docker compose -p pedigree-rt003 logs --no-color                > "$S\case1-logs.txt"
docker inspect pedigree-rt003-pedigree-1                        > "$S\case1-inspect.txt"
# exact-value scan of every captured file, plus token-shaped regex scan
```

Observed:

- Tracked by git: `0` matches (`demo-demo.json` is neither tracked nor present in the
  clone's working tree before runtime).
- Image ships no credential: a fresh `docker run` of `pedigree:local` shows
  `/data/credentials` **empty**, mode `700`, uid/gid `10001:10001` (created by the
  Dockerfile build, not by seeding). `find / -xdev -name 'demo-*.json'` → nothing.
  Only matches for `*credential*` are unrelated library files
  (`redis/credentials.py`, `mcp/client/auth/.../client_credentials.py`).
- Runtime container as user `10001(pedigree)`:

```text
drwx------ 2 pedigree pedigree 4096 /data/credentials
-rw------- 1 pedigree pedigree  235 /data/credentials/demo-demo.json
600 10001:10001 /data/credentials/demo-demo.json
```

- Exact-token-value match counts (agent token, operator token, legacy token):
  `case1-env.txt=0`, `case1-logs.txt=0`, `case1-inspect.txt=0`, `case1-image.txt=0`,
  `compose-up.log=0`.
- Token-shaped regex across **all 64 evidence files except the credential copy itself**:
  `exact_token_matches=0`, `token_shaped_matches=0`. Only `demo-demo.json` in `$S`
  contains credential values (and `scratch/` is gitignored: `.gitignore:31:scratch/`).
- Logs do show the file **path**: `[seed] local credential file: /data/credentials/demo-demo.json (keep private; never commit)` — path only, no value.

Result: PASS.

## Case 2 — Deployment-admin surface in demo mode (`PEDIGREE_ENV=production`, `PEDIGREE_SEED_DEMO=1`)

```powershell
$FAKE='ped_admin_FAKEtokenShapeNotReal000000000000000000'
curl.exe -s -o "$S\body-admin-none.txt"    -w "GET /admin/tenants no-header -> %{http_code}" $U/admin/tenants
curl.exe -s -o "$S\body-admin-any.txt"     -w "GET /admin/tenants X-Admin-Token:anything -> %{http_code}" -H "X-Admin-Token: anything" $U/admin/tenants
curl.exe -s -o "$S\body-admin-shaped.txt"  -w "GET /admin/tenants X-Admin-Token:<token-shaped> -> %{http_code}" -H "X-Admin-Token: $FAKE" $U/admin/tenants
curl.exe -s -o "$S\body-admin-post.txt"    -w "POST /admin/tenants valid-json token-shaped -> %{http_code}" -X POST -H "Content-Type: application/json" -H "X-Admin-Token: $FAKE" --data-binary "@$S\body-create.json" $U/admin/tenants
curl.exe -s -o "$S\body-admin-post-malformed.txt" -w "POST /admin/tenants malformed-json no-header -> %{http_code}" -X POST -H "Content-Type: application/json" --data-binary "@$S\body-malformed.json" $U/admin/tenants
curl.exe -s -o NUL -w "GET /metrics no-header -> %{http_code}" $U/metrics
curl.exe -s -o NUL -w "GET /metrics token-shaped -> %{http_code}" -H "X-Admin-Token: $FAKE" $U/metrics
curl.exe -s -o NUL -w "GET /docs -> %{http_code}" $U/docs
curl.exe -s -o NUL -w "GET /openapi.json -> %{http_code}" $U/openapi.json
curl.exe -s -o NUL -w "GET /redoc -> %{http_code}" $U/redoc
curl.exe -s -o NUL -w "GET /readyz -> %{http_code}" $U/readyz
curl.exe -s -o NUL -w "GET /v1/stats no-header -> %{http_code}" $U/v1/stats
curl.exe -s -o NUL -w "POST /v1/admin/resume no-header -> %{http_code}" -X POST -H "Content-Type: application/json" --data-binary "@$S\body-resume.json" $U/v1/admin/resume
curl.exe -s -o NUL -w "POST /v1/admin/resume token-shaped -> %{http_code}" -X POST -H "Content-Type: application/json" -H "X-Admin-Token: ped_admin_FAKE000" --data-binary "@$S\body-resume.json" $U/v1/admin/resume
```

Observed:

```text
GET  /admin/tenants no-header                        -> 403
GET  /admin/tenants X-Admin-Token: anything          -> 403
GET  /admin/tenants X-Admin-Token: <token-shaped>    -> 403
POST /admin/tenants valid-json + token-shaped header -> 403
POST /admin/tenants malformed-json no-header         -> 422   <-- F2
GET  /metrics no-header                              -> 403
GET  /metrics token-shaped                           -> 403
GET  /docs / /openapi.json / /redoc                  -> 404 / 404 / 404
GET  /readyz                                         -> 200 {"ready":true}
GET  /v1/stats no-header                             -> 401
POST /v1/admin/resume no-header / token-shaped       -> 403 / 403
```

Bodies are the typed envelope with no stack traces or field details, and the 403 is
indistinguishable from a wrong token (`operation forbidden`), so demo mode leaks
nothing about the admin token. `/docs`, `/openapi.json` and `/redoc` are absent because
`PEDIGREE_ENV=production` and `PEDIGREE_PUBLIC_DOCS` is unset (`api/app.py:134`).

Related payload-boundary probes:

```powershell
# 3 MB declared body / 300 KB chunked body / raw-socket duplicate Content-Length
POST /admin/tenants declared-3MB  -> 413 {"error":{"code":"too_large",...}}
POST /admin/tenants chunked-300KB -> 413 (curl exit 0)
raw socket duplicate Content-Length -> HTTP/1.1 400 Bad Request / "Invalid HTTP request received."
```

Result: PASS, with F2 (low).

## Case 3 — Network exposure

```powershell
docker compose -p pedigree-rt003 port db 6379                  # -> "invalid IP:0" (see F5)
docker port pedigree-rt003-db-1                                # -> (empty)
docker inspect pedigree-rt003-db-1 --format '{{json .NetworkSettings.Ports}}'
# -> {"6379/tcp":null}
docker inspect pedigree-rt003-pedigree-1 --format '{{json .NetworkSettings.Ports}}'
# -> {"8000/tcp":[{"HostIp":"127.0.0.1","HostPort":"8012"}]}
Get-NetTCPConnection -State Listen -LocalPort 8012 |
    Select-Object LocalAddress,LocalPort,OwningProcess        # -> 127.0.0.1 8012 com.docker.backend (pid 32784)
curl.exe -s -o NUL -w "%{http_code}" --max-time 5 http://127.0.0.1:8012/readyz   # -> 200
foreach ($ip in '192.168.1.8','172.18.224.1','100.102.59.123') {
    curl.exe -s -o NUL -w "%{http_code}" --max-time 4 "http://${ip}:8012/readyz"  # -> 000, curl exit 7
    Test-NetConnection -ComputerName $ip -Port 8012 -InformationLevel Quiet      # -> False
}
$dbip = docker inspect pedigree-rt003-db-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
Test-NetConnection -ComputerName $dbip -Port 6379 -InformationLevel Quiet        # -> False
```

Observed:

- DB has **no host publication** (`{"6379/tcp":null}`; `docker port` empty). Host
  cannot reach the DB container IP on 6379 either.
- API published on `127.0.0.1:8012` only; the host listener is bound to `127.0.0.1`
  (`com.docker.backend` port forwarder).
- Host probes on the Wi-Fi LAN address `192.168.1.8`, the WSL address `172.18.224.1`
  and the Tailscale address `100.102.59.123` all fail: `curl` exit 7 / HTTP `000`,
  `TcpTestSucceeded=False`. Loopback probe returns 200, so the failures are binding,
  not a dead service.
- `docker compose config` with `PEDIGREE_PORT=8012` resolves to
  `host_ip: 127.0.0.1`, `published: "8012"`; the mapping template
  `127.0.0.1:${PEDIGREE_PORT:-8000}:8000` cannot be tricked into a non-loopback bind by
  a `PORT`-style value (the host IP is literal in the compose file).

Result: PASS.

## Case 4 — Proxy/peer trust

Inspected rather than brute-forced:

- `scripts/entrypoint.sh` (both `1c1ce2a` and HEAD) runs
  `python -m uvicorn ... --no-proxy-headers`; PID 1 inside the running container
  confirms the effective command:
  `python -m uvicorn pedigree.api.app:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers`
  (uvicorn 0.54.0).
- `src/pedigree/api/auth.py:12-20`: `peer()` returns `request.client.host` (the ASGI
  transport peer) and `check_peer` uses it only for the rate limiter; there is no
  header-derived identity and no header-based privilege anywhere.

Runtime probes:

```powershell
# real operator token from the credential copy, held only in a PowerShell variable
curl.exe ... -H "Authorization: Bearer $op"                                     # A -> 200
curl.exe ... -H "Authorization: Bearer $op" -H "X-Forwarded-For: 10.0.0.9" -H "X-Real-IP: 10.0.0.9" -H "Forwarded: for=10.0.0.9"   # B -> 200
curl.exe ... -H "Authorization: Bearer $agent"                                  # C -> 200
curl.exe ... -H "Authorization: Bearer ped_a_nobody_invalid" -H "X-Forwarded-For: 10.0.0.9"  # D -> 401
curl.exe ... -H "X-Forwarded-For: 10.0.0.9" -H "X-Admin-Token: ped_admin_FAKE000" /admin/tenants  # E -> 403
docker compose -p pedigree-rt003 logs --no-color --since 40s pedigree
```

Observed: A/B/C/D/E statuses are `200/200/200/401/403` — identical with and without
the forged headers. The access log proves why:

```text
INFO:     172.19.0.1:38158 - "GET /v1/stats HTTP/1.1" 200 OK
INFO:     172.19.0.1:38170 - "GET /v1/stats HTTP/1.1" 200 OK
INFO:     172.19.0.1:38174 - "GET /v1/stats HTTP/1.1" 200 OK
INFO:     172.19.0.1:38176 - "GET /v1/stats HTTP/1.1" 401 Unauthorized
```

The logged client is the real Docker peer `172.19.0.1`, and `10.0.0.9` appears **0**
times in the log — `X-Forwarded-For`/`X-Real-IP`/`Forwarded` never reach
`request.client`.

Honesty note: demo mode 403s every admin route regardless of header, so this probe
cannot distinguish admin-token comparison behaviour; what it does establish is that the
transport peer (and therefore the limiter key) is not header-settable. The admin token
comparison (`hmac.compare_digest`, `routes/admin.py:17`) is only observable in a
non-demo stack, which is P-013's surface, not this one.

Result: PASS.

## Case 5 — Seed fail-closed

### 5a. Missing credential file

```powershell
docker compose -p pedigree-rt003 exec -T pedigree rm /data/credentials/demo-demo.json   # exit 0
docker compose -p pedigree-rt003 exec -T pedigree ls -la /data/credentials             # empty
docker compose -p pedigree-rt003 restart pedigree                                       # exit 0
docker compose -p pedigree-rt003 ps -a
docker inspect pedigree-rt003-pedigree-1 --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}} Error={{.State.Error}}'
docker compose -p pedigree-rt003 logs --no-color --tail 12 pedigree
curl.exe -s -o NUL -w "%{http_code}" --max-time 3 http://127.0.0.1:8012/readyz          # exit 7
```

Observed:

```text
pedigree-rt003-pedigree-1   Exited (1) 3 seconds ago
Status=exited ExitCode=1 Error=
[runtime] database module42201 and mandatory limits verified
[seed] failed: existing demo tenant has no local credential file; restore the private file or choose a new dedicated PEDIGREE_DEMO_TENANT
[seed] seeding errors stop startup; nothing was deleted
curl /readyz -> 000 (exit 7)
```

The failure is actionable, names no credential, and the API never comes up — fail-closed.

### 5b. Revoked tenant (runtime reproduction achieved)

```powershell
docker compose -p pedigree-rt003 exec -T db redis-cli GRAPH.QUERY ped:registry "MATCH (t:Tenant {id:'demo'}) SET t.status='revoked' RETURN t.id, t.status"
# -> demo / revoked, Properties set: 1
docker compose -p pedigree-rt003 restart pedigree
docker inspect pedigree-rt003-pedigree-1 --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}}'
```

Observed: container `exited`, `ExitCode=1`, log:

```text
[seed] failed: demo tenant is revoked; choose a new dedicated demo tenant
[seed] seeding errors stop startup; nothing was deleted
```

This matches the committed unit/integration expectations
(`scripts/seed_demo.py::SeedError` "demo tenant is revoked; choose a new dedicated
demo tenant"; `tests/integration/test_p003_runtime.py::
test_seed_refuses_revoked_demo_tenant_with_actionable_error` and
`::test_seed_boot_fails_if_existing_tenant_has_no_local_credential`). Note the graph
mutation used direct `redis-cli` because no HTTP/CLI revoke path exists in demo mode;
the isolation is unchanged (tenant `demo`, project `pedigree-rt003` only).

Result: PASS.

## Case 6 — Additional boundaries

- Volume ownership/perms: `/data` and `/data/credentials` are `700 10001:10001`; the
  credential file is `600 10001:10001`; the process runs as `10001(pedigree)`. The
  named volume `pedigree-rt003_pedigree-state` has no secrets in its labels/metadata.
- `docker compose ls` / `config` / `inspect`: no credential or `PEDIGREE_ADMIN_TOKEN`
  anywhere. The container env is only
  `PEDIGREE_SEED_DEMO`, `PEDIGREE_DEMO_TENANT`, `PEDIGREE_CREDENTIALS_DIR`,
  `FALKOR_HOST`, `FALKOR_PORT`, `PEDIGREE_ENV` plus runtime defaults. (A scan count of
  `1` for `ADMIN_TOKEN` in `case6-config.txt` is the probe's own echo header line, not
  a config value — verified by reading the file.)
- Healthcheck command (`docker inspect .Config.Healthcheck`): `sh -c python -c "...`
  reading `PORT`/`8000` `/readyz`; contains no secret. `/readyz` unauthenticated
  returns only `{"ready":true}` (needed by the Docker healthcheck).
- Unauthenticated MCP: `initialize` → 200 (protocol-level), `tools/list` → 200 with
  the tool inventory, `tools/call pedigree_health` → 200
  `{"ok":true,"ready":true,"module_version":42201}` (F1). `tools/call pedigree_remember`
  without a credential → HTTP 200 with `{"ok":false,"error":{"code":"unauthorized"...}}`,
  i.e. writes are correctly refused (with the F6 semantics note).
- Token rotation: CLI `admin issue-operator --id demo --rotate` → exit 0, new token
  differs from the old; afterwards old operator token → **401**, new → 200, agent token
  → 200. Old credentials do not survive rotation.
- Demo-mode CLI: `python -m pedigree.cli admin create-tenant --id rt003probe` → exit 0
  and JSON credentials, with **no** `PEDIGREE_ADMIN_TOKEN` set (F3).
- Static/traversal: `/`, `/../scripts/seed_demo.py`, `/..%2fscripts%2fseed_demo.py`,
  `/data/credentials/demo-demo.json` → `200` (UI) / `404` ×3, no file contents.
- Raw socket duplicate `Content-Length` → `400 Bad Request` at the HTTP parser.
- Evidence hygiene: 64 probe files scanned for token values and token-shaped strings →
  0 matches in everything except the intentional credential copy; `scratch/` is
  gitignored, and the main repo shows no modification by this session.

## Findings

| id | Attack surface | Expected | Observed | Defect? | Severity | Test id (proposed; not added — findings-only mandate) |
|---|---|---|---|---|---|---|
| F1 | MCP `/mcp`: `initialize`, `tools/list`, `tools/call pedigree_health` with no credential | Credential required for any session or tool result | 200 + full tool inventory + `{"ok":true,"ready":true,"module_version":42201}` | Yes — unauthenticated info disclosure; no tenant data, no writes | Low locally (loopback-only); would be Medium if `/mcp` is publicly routed (unverified) | `tests/security/test_redteam_p003_runtime.py::test_mcp_health_and_tools_list_require_credential` |
| F2 | `POST /admin/tenants` (demo-disabled) with malformed JSON | Deny (403) regardless of body | `422 invalid_argument` before the admin check | Yes — route-existence/validation oracle on a disabled route; no data, no state change | Low | `tests/security/test_redteam_p003_runtime.py::test_demo_admin_route_denies_before_body_validation` |
| F3 | CLI `admin create-tenant` / `issue-operator` in demo mode with no admin token | Refuse without a deployment credential | Exit 0, prints credentials | No (same trust domain: exec/host access already reads `/data/credentials`; not network-reachable) — document it | Info | `tests/security/test_redteam_p003_runtime.py::test_cli_admin_bootstrap_is_documented_in_demo_mode` |
| F4 | Operator rotation vs. on-disk credential file | Old token invalid; operator can recover | Old token invalid (401); file keeps the stale operator token until re-seed | No — operational trap, covered by the seed message | Info | n/a |
| F5 | `docker compose port db 6379` | Empty | `invalid IP:0`, exit 0 (Compose v5.5.1) | No — tooling quirk; use `docker inspect .NetworkSettings.Ports` | Info | n/a |
| F6 | MCP unauthorized tool result | Agent-detectable failure | HTTP 200, `isError:false`, payload `{"ok":false,...}` | No (structured-error convention) — flag for agent clients | Info | n/a |

### F1 — minimal reproduction (do not fix here)

```powershell
$U='http://127.0.0.1:8012'
curl.exe -s -D - -X POST -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" `
  --data-binary "@$S\mcp-init.json" $U/mcp          # -> 200, mcp-session-id header
# replay with the session header from the response, no Authorization:
curl.exe -s -X POST -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Session-Id: <from init>" --data-binary "@$S\mcp-tools.json" $U/mcp      # -> 200 tool inventory
curl.exe -s -X POST ... --data-binary "@$S\mcp-call-health.json" $U/mcp
# -> {"ok": true, "ready": true, "module_version": 42201}
```

Root cause in code: `src/pedigree/mcp_server.py` registers `pedigree_health()` without
`_resolve()` (unlike every data tool), and the SDK serves `initialize`/`tools/list`
before tool handlers run. Suggested fix direction (not applied): gate `/mcp` in
`RootDispatcher` with a bearer check before handing to the MCP ASGI app, or make
`pedigree_health` `_resolve`-gated and drop `module_version` from its anonymous reply.

### F2 — minimal reproduction

```powershell
'{"id":"rt003new",' | Set-Content -NoNewline "$S\body-malformed.json" -Encoding ASCII
curl.exe -s -X POST -H "Content-Type: application/json" --data-binary "@$S\body-malformed.json" $U/admin/tenants
# -> 422 {"error":{"code":"invalid_argument","message":"invalid argument",...}}   (no header sent)
```

Root cause: `routes/admin.py` calls `_require_admin` inside the route body, so FastAPI
validates `payload: TenantCreate` first. Suggested fix direction: perform the admin
check in a `Depends(...)` (dependencies run before body parsing), or do not register
admin/metrics routes at all when `settings.pedigree_seed_demo` is true — mirroring how
`docs_url` is dropped in production.

## Limitations and open questions

- Loopback single-host testing only: the committed compose publishes the API on
  `127.0.0.1`. I could not and did not verify any public deployment's edge routing, so
  F1's exposure there is unmeasured.
- Demo mode sets no `PEDIGREE_ADMIN_TOKEN`, so the runtime admin-token comparison path
  (`hmac.compare_digest`) was not exercised; it was inspected in source and is covered
  by `tests/security/test_admin_auth.py` elsewhere. A non-demo public stack (P-013) is
  the right place to probe that path.
- No reverse proxy is in the request path, so "proxy distrust" is demonstrated by
  `--no-proxy-headers` + the unchanged logged peer identity, not by a real
  proxy-in-front scenario. Under a future proxy, disabling proxy headers would collapse
  all rate-limit peers to the proxy address (granularity consideration, not a bypass).
- Windows firewall could contribute to the LAN/WSL/Tailscale refusals; the authoritative
  evidence is the Docker port binding (`{"8000/tcp":[{"HostIp":"127.0.0.1",...}]}`) and
  the loopback-only host listener. The DB refusal has two independent signals
  (`{"6379/tcp":null}` and host-unreachable container IP).
- Anyone with Docker socket / `exec` access is root-equivalent here (can read
  `/data/credentials`, mutate the registry graph, run the CLI). That is inherent to a
  single-host compose deployment and is why F3 is informational, not an escalation.
- The revoked-tenant and rotation probes mutated only the isolated `pedigree-rt003`
  demo graph; the stack was torn down with `down -v` afterwards (see cleanup note).
- Cleanup: `docker compose -p pedigree-rt003 down -v` was run from the clone at the end
  (recorded in `scratch/qa-redteam-p003/cleanup.txt`); the clone and scratch evidence
  were left in place uncommitted.
