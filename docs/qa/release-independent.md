# Independent release QA / red-team

**Verdict: FAIL at release commit `2947c30`.** One product regression is red;
checkpoint/recovery acceptance is incomplete and one architectural claim is contradicted.
Review-only tests/docs; no product edits, push, PR or original application/volume access.

## Scope and isolation

Reviewed `fbf6538..2947c30`: production defaults `fa42c41`, tenant ACL `ded717d`,
admin resume `7a74c07`, WCC `ed89210`, startup lock `1f50757`, UI `bb448c4`,
spool `c3da55d` and scoped failure injection `3ad6de9`, plus consult 014 acceptance
`2947c30`. Read canonical instructions, handoff/progress, ADRs, architecture, operating
protocol and QA/red-team roles. Work area: independent release acceptance evidence.

First commands:

```powershell
git status --short --branch
git merge --ff-only release/production-completion-20261018
```

Output: clean `t3/cfe8bc2a`; `Updating fbf6538..2947c30`, `Fast-forward`, exit 0.
Runtime: supplied virtualenv, Python 3.12.15, own checkout's `src` on PYTHONPATH.
The executable is supplied through `QA_PYTHON` below. Its machine-specific absolute
path is intentionally not tracked. No new dependencies were installed.

```powershell
docker run -d --name pedigree-independent-qa-20261018-6385 -p 127.0.0.1:6385:6379 falkordb/falkordb:v4.22.1 redis-server --loadmodule /usr/lib/redis/modules/falkordb.so --appendonly no --save "" --protected-mode no
docker inspect pedigree-independent-qa-20261018-6385 --format '{{json .Mounts}}'
```

Exit 0; mounts `[]`; module independently read as `42201`. No original volume was
attached. Existing containers were listed by name/image/port only. The disposable DB
admin connection is unauthenticated; raw ACL attacks use separately authenticated
tenant identities. This is not proof of the default Compose database-password setup.

## Findings

### F1 / P2 / High confidence: metadata bridges contaminate WCC partitions

Location: `src/pedigree/db/queries.py:412`, ADR-016 `docs/DECISIONS.md:474`.
WCC selects every `Node`, including Sessions, and filters Source/Memory/Action only
AFTER connectivity calculation. Metadata can join otherwise separate lineage components.

Reproduce against the owned DB with:

```powershell
& $env:QA_PYTHON -m pytest -q tests/security/test_release_independent.py::test_wcc_excludes_metadata_as_connectivity_bridges
```

The regression sends this body through `/v1/events` under an agent bearer:

```json
{"runtime":"generic","session_id":"session","events":[{"type":"session"},{"type":"action_executed","id":"a","tool":"Read","relied_on":["session"]},{"type":"action_executed","id":"b","tool":"Read","relied_on":["session"]}]}
```

Observed HTTP 200, then:

```text
{'components': [{'component': 0, 'nodes': 2}], 'truncated': False,
 'note': 'weak connectivity over derivation and corroboration; component IDs are snapshot-local'}
assert [2] == [1, 1]
```

Capability verdict: an authenticated agent can distort its own component summary.
No cross-tenant escape demonstrated. Session dependencies were already accepted;
the new component query violates its documented metadata exclusion. Fix: exclude
metadata from the algorithm's INPUT projection. Preserve this failing regression
and add other history-label bridge cases. No xfail or assertion relaxation added.

### F2 / P2 / High confidence: graph replacement impossibility claim is false

Location: `docs/DEVELOPMENT_HANDOFF.md:322-328`. The acceptance evidence probes
GRAPH.COPY and absent GRAPH.RENAME, then concludes atomic in-place replacement is
impossible and staged writes are the only replacement path. It misses privileged
Redis `RENAME`. An independent raw probe over two existing synthetic graphs returned:

```text
RENAME: True
destination: [['new']]
source_exists: 0
```

Destination previously contained `old`. The passing committed test additionally
checks GRAPH.LIST source absence/destination membership and tenant RENAME denial:

```powershell
& $env:QA_PYTHON -m pytest -q tests/security/test_release_independent.py::test_admin_redis_rename_replaces_existing_graph
```

Capability verdict: privileged graph-key replacement is available in this simple
live probe. This does NOT prove safe concurrent replacement, persistent rename
semantics, crash behavior, index behavior after restart, rollback or implemented
restore. Correct the impossibility claim and evaluate this primitive before relying
on that architectural exclusion. Future recovery design was not reviewed as shipped.

### F3 / P2 / High confidence: checkpoint acceptance remains unproven

Location: `docs/DEVELOPMENT_HANDOFF.md:313-321,333-334` and consult 014 decision's
acceptance paragraph. The heading "Checkpoint/failure recovery" cites startup
locking, checkpoint-name validation, ACL namespace permission and launch config.
None creates a checkpoint, restores state, injects restore failure or demonstrates
rollback. The final "Remaining release work" list omits this unimplemented requirement.

The evidence does NOT explicitly claim restore is built: it says "Restore stays
explicitly unbuilt and is not claimed"; consult 014 says its responses are not
executed evidence. Those caveats are accurate. The heading and closing remaining-work
list nevertheless overstate acceptance coverage. Rename this item to startup/config
validation and keep checkpoint/restore acceptance explicitly OPEN. Unfinished recovery
and OpenCode capture were not treated as implemented or accepted features.

## Independent adversarial attempts

These are new probes in `tests/security/test_release_independent.py`, beyond rerunning
builder tests. PASS describes only the attempted capability.

| Attack | Observed result |
| --- | --- |
| Raw GET/SET/DEL of foreign graph/checkpoint, registry aliases, prefix-confusable graph and foreign mutex | PASS: actual permission errors, foreign mutex/registry preserved |
| EVAL with foreign ARGV key and declared KEYS key | PASS: permission errors; scripts cannot bypass ACL |
| Raw GRAPH.COPY and GRAPH.RO_QUERY on foreign/prefix/registry families | PASS: permission errors, no privileged fallback |
| REST tenant query/header spoofing and fake admin header | PASS: bearer tenant retained, foreign Source absent |
| MCP valid bearer plus conflicting tenant claim | PASS: structured unauthorized, foreign data unchanged |
| Agent human-source/trusted-integrity durable events and MCP trust claim | PASS: forbidden before receipt/session mutation |
| Agent human/scanner corroboration; foreign operator against local IDs | PASS: 403/404, no trusted support edge |
| Lost/wrong outbox acknowledgement | PASS: exact envelope retained until matching acknowledgement |
| Credential switch while old spool pending | PASS: old spool refuses send; new namespace empty; old credential drains original |
| Same receipt ID across tenants; changed payload; replay at full cap | PASS: separate receipts, altered body 409, exact replay succeeds, new receipt quota_exceeded, three nodes/invariants preserved |
| Startup repair racing real revoke under lifecycle lock | PASS: worker waits, root remains revoked, invariants clean |
| WCC receipt/Session READ metadata plus populated foreign graph | PASS: only own lineage counted, foreign limit truncation explicit |
| WCC DERIVED_FROM metadata bridge created by REST | FAIL F1: partitions merged |
| Empty/default admin credential in production | PASS: startup rejected |
| Nonloopback peer with forged X-Forwarded-For and local demo enabled | PASS: config hides demo and demo-session route returns 403 |
| Privileged Redis RENAME replacement plus tenant denial | Primitive PASS; contradicts F2 claim |

Remote peer is a synthetic ASGI transport input, not a real remote/browser session.
No installed Claude/OpenCode runtime execution is claimed.

## Commands and real output

Selections ran serially against owned 6385 with this environment. First two used
the same supplied executable directly; `QA_PYTHON` abstracts only that local path.

```powershell
$env:FALKOR_HOST='127.0.0.1'
$env:FALKOR_PORT='6385'
$env:PEDIGREE_ENV='test'
$env:PYTHONPATH=(Join-Path $PWD src)
& $env:QA_PYTHON -m pytest -q tests/security/test_tenant_db_service.py tests/integration/test_capture_delivery.py tests/integration/test_components.py tests/integration/test_ui_configuration.py tests/unit/test_startup_maintenance.py tests/unit/test_production_launch.py tests/unit/test_capture_spool.py
```

Exit 0: `38 passed in 13.79s`.

```powershell
& $env:QA_PYTHON -m pytest -q tests/integration/test_api.py tests/integration/test_mcp.py tests/integration/test_whatif.py tests/integration/test_revoke_resume.py tests/unit/test_config.py tests/unit/test_claude_hook.py
```

Exit 0: `68 passed in 12.02s`.

```powershell
& $env:QA_PYTHON -m pytest -q tests/security/test_release_independent.py
```

Final exit 1: **`1 failed, 9 passed in 4.09s`**, sole failure F1 above.
Early review-harness runs had an MCP response-attribute error, wrong keyword-only
revoke invocation and temporary indentation error. Corrected before final results;
not product defects or passing gates. Only the small independent file was rerun as
probes were refined; builder selections were not repeated as broad duplicate suites.

### Production-mode HTTP and restart probe

```powershell
$env:INDEPENDENT_QA_CONTAINER='pedigree-independent-qa-20261018-6385'
& $env:QA_PYTHON tests/security/release_runtime_probe.py
```

Exit 0:

```text
EMPTY: module 42201; zero tenants; no mounted volumes
PRODUCTION: ready=200; tenants=[]; demo=false; docs=false/404
API RESTART: same persisted receipt acknowledged
DB RESTART: persisted source/receipt; ACL reprovisioned; exact replay; one source
CLEANUP: owned API stopped; exact synthetic graph/tenant removed
```

The manual probe verifies container name/image/port/mounts, generates private
credentials, launches its own loopback uvicorn process, enables AOF/fsync on this
disposable DB, restarts ONLY that container, and removes its exact tenant/graph.
A graceful restart of the same container filesystem is proven. Host failure,
production volume durability/migration, default Compose image build, database-admin
password enforcement and backup restore are not established by this probe.
Empty startup and persisted receipt evidence came from HTTP, not configuration alone.

### Repository hygiene

```powershell
& $env:QA_PYTHON -m ruff check .
& $env:QA_PYTHON scripts/secret_scan.py --history
& $env:QA_PYTHON scripts/check_numbers.py
& $env:QA_PYTHON scripts/check_readme.py
```

All exit 0:

```text
All checks passed!
[secret-scan] PASS: no credential shapes found in tracked files or git history
[check-numbers] PASS: 4 file(s) checked against 70 allowed values
[check-readme] PASS: 11 headings, docs/*.md links, numbers
```

Secret scanner was invoked directly from the supplied virtualenv with `--history`,
the same operation used by `scripts/check_secrets.sh`; its wrapper expects a local
`.venv` which this checkout lacks. Review files were staged for scanning. Final
lint, history-inclusive secret scan, numbers and README checks all passed after the
corroboration probe/report update. No full `make check` result is claimed.

## Residuals and handoff

Release is NOT independently accepted until F1 is fixed and checkpoint/recovery
acceptance is verified or explicitly deferred with honest release scope. Correct F2/F3.
Retain the red regression as repair acceptance. No tenant escape was found in the
tested raw Redis/REST/MCP cases. Startup locking and capture replay passed within the
single-process/stable-primary boundaries.

No heavy perf, full dogfood, browser visual, hosted preview, Render billing/deployment,
TestSprite, installed-runtime capture, physical-device or off-host recovery result is
claimed. Review changed no traversal/revoke/gate product implementation. Original
crashed volume and running application data remained untouched. This review commit
intentionally includes a failing regression, as requested; it is not a green release
commit. No push is authorized or performed.

Final cleanup independently verified `zero tenants; registry schema only`, then
`docker stop pedigree-independent-qa-20261018-6385` exited 0. Only this owned review
container was stopped; its disposable filesystem is retained for inspection.
