# Independent release review, round two

Reviewed release head **b33d980** (2026-10-18). **Scoped checks PASS; release
acceptance remains OPEN.** Prior F1 is repaired; F2/F3 wording is corrected.
Checkpoint/restore acceptance and native restart durability remain OPEN. No product
edits, push, subagents, hosted deployment or original application/volume access.

## Scope, acceptance and isolation

Acceptance was defined by the review brief: reproduce the prior WCC failure, verify
metadata exclusion and union semantics on pinned real FalkorDB, rerun the selected
production/ACL/startup/UI/Claude checks, independently attack observed native
write/edit/bash handling, and preserve unfinished recovery/durability objections.
Read AGENTS, handoff, CURRENT STATE, ADRs, architecture, operating protocol and
qa-senior/red-team roles. Review area is this report and review tests only; the
explicit docs/tests-only brief takes precedence over editing the shared status board.

The clean review branch `t3/independent-release-review-round2` started at fbf6538:

```powershell
git status --short
git merge --ff-only release/production-completion-20261018
```

Exit 0: `Updating fbf6538..b33d980`, `Fast-forward`. No unrelated changes present.
Node `v24.13.1`; Docker server `29.8.2`. Existing supplied virtualenv is referenced
as `$env:QA_PYTHON`; no dependency installation. Own checkout's `src` is PYTHONPATH.

```powershell
docker run -d --name pedigree-round2-6389 -p 127.0.0.1:6389:6379 falkordb/falkordb:v4.22.1 redis-server --loadmodule /usr/lib/redis/modules/falkordb.so --appendonly no --protected-mode no
docker inspect pedigree-round2-6389 --format '{{json .Mounts}}'
```

Exit 0; mounts `[]`; independently verified module `42201`. New disposable container,
no mounted original volume. Only DB6389 was used. The disposable admin connection
is unauthenticated; tested tenant connections use real ACL credentials. This does
not prove Compose's database password or hosted storage configuration.

**Scope deviation:** existing `test_capture_delivery` and `test_claude_hook` fixtures
open test-owned loopback servers on dynamically allocated ports. I missed those
fixture internals before their rerun, contrary to the requested API8119-only bound.
Their teardown terminates/closes those servers. The new independent native suite
and production/restart probe explicitly use API8119. No existing application's
endpoint, data or volume was accessed. The initial selected-suite invocation lost
its completion output in the tool wrapper; no pass count is inferred from it. The
recorded completed rerun below supplies the evidence.

## Per-area verdicts

| Area | Verdict and evidence | Remaining boundary |
| --- | --- | --- |
| Production defaults | PASS for source/configuration and owned production HTTP: empty tenant list, demo false, docs false/404; missing/default admin rejected | Compose image build/password enforcement and hosted persistence were not exercised |
| Token-selected tenant ACL, REST/MCP/admin | PASS for real ACL foreign graph/registry/script/copy/prefix denial; spoofed tenant claims do not select another graph; provisioning failure returns 503; REST/MCP/admin resume use scoped identities | Stable-primary/single-service model; raw tenant DB credentials are infrastructure credentials, not exposed bearer API credentials |
| WCC | PASS; original regression green; six additional metadata bridge combinations excluded; three input labels union correctly; multi-label node counted once | Bounded snapshot summary, no performance claim |
| Startup serialization | PASS; real revoke/repair interleaving waits on lifecycle lock, revoked source preserved, invariants clean | Single-process lock, not distributed lifecycle coordination |
| UI capability visibility | PASS for HTTP config/HTML and remote-peer spoof checks | No browser rendering/interaction proof |
| Claude durable capture/receipts | PASS for focused outbox/receipt failures, offline subprocess capture/replay, partial writes, quota/replay identity and owned HTTP/API/DB restart checks | Not an installed Claude session, host crash, off-host backup or recovery acceptance |
| Native OpenCode capture | PASS for tested callbacks over real HTTP/DB and builder focused Node tests independently executed | Simulated runtime operations in this review; builder installed evidence remains separately attributed; no restart durability |
| Recovery | OPEN; corrected handoff explicitly distinguishes startup/configuration from restore acceptance | New recovery implementation is not merged at reviewed head and was not reviewed |

## Prior objections and reproduction

**F1 closed for the tested partition semantics.** `src/pedigree/db/queries.py:412`
now supplies `nodeLabels:['Source','Memory','Action']` to WCC itself. To reproduce
the prior red result without editing product files or changing the review head,
substitute only the old query in the current Python process and run the unchanged
original regression against real DB6389:

```powershell
@'
import ast, subprocess, pytest
import pedigree.engine.components as components
source = subprocess.check_output(['git','show','2947c30:src/pedigree/db/queries.py'], text=True)
assignment = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'Q_WCC_SUMMARY' for t in n.targets))
components.Q_WCC_SUMMARY = ast.literal_eval(assignment.value)
raise SystemExit(pytest.main(['-q','tests/security/test_release_independent.py::test_wcc_excludes_metadata_as_connectivity_bridges']))
'@ | & $env:QA_PYTHON -
```

Expected exit **1**, actually observed:

```text
AssertionError: {'components': [{'component': 0, 'nodes': 2}], 'truncated': False, ...}
assert [2] == [1, 1]
1 failed in 1.51s
```

This isolates the old query, rather than claiming an entire old checkout was run.
The unchanged regression passes at b33d980 in the focused selection below.
New `test_metadata_bridges_excluded_before_wcc` checks Session/Agent/Revocation,
each with DERIVED_FROM and CORROBORATED_BY bridges, expecting `[1,1]`.
`test_wcc_label_union_counts_multilabel_once` creates distinct Source, Memory and
Action nodes in one mixed component plus a Source:Memory:Action singleton and
excluded Session. Observed `[1,3]`, no truncation: union, not intersection, and no
duplicate counting. All are actual algorithm executions, not query-string checks.

**F2 closed as a wording defect.** Handoff line 322 now acknowledges privileged
Redis RENAME. The original actual graph replacement/tenant-denial regression passed
again. Primitive availability still does not establish concurrent, crash-safe restore.

**F3 closed as a wording defect; acceptance remains OPEN.** Handoff lines 313 and
327 call the tested area startup/configuration and explicitly retain recovery work.
There is no claim here that heading correction implements recovery.

## Independent native attacks

`tests/security/release_round2_native.mjs` imports the product core, not builder test
helpers. `test_independent_native_attacks_real_http_db` runs it against the actual
API8119 and real graph with an agent bearer. Each case has a unique runtime session.
Filesystem writes/edits and callback delivery are simulated explicitly; this is not
installed OpenCode execution. Every malformed callback also attempts a later tool
and verifies the incomplete latch denies it.

| Attack | Actual result |
| --- | --- |
| Write disk bytes differ from intended content | No Action; later tool denied |
| Edit correct full post-state with private old/new/body/diff canaries | Exactly matching full-file artifact digest; no canaries or absolute root in API bodies |
| Edit includes extra concurrent change | No Action; later tool denied |
| New file through escaping junction plus nonexistent intermediate directory | Rejected before any gate/network call; outside directory not created |
| Bash missing exit | No Action; later tool denied |
| Bash nonzero exit 12 | No Action; later tool denied |
| Bash string exit "0" | No Action; later tool denied |
| Bash wrapper/metadata output disagreement | No Action; later tool denied |
| Changed command arguments on callback | No Action; later tool denied |
| Foreign call ID | No Action; later tool denied |
| Changed tool identity | No Action; later tool denied |
| .env.production, mixed-case .AWS/credentials, PEM, git credential and SSH paths | All denied before networking |
| Successful Bash command/output privacy and risk | Unknown/high Action and output hash only; persisted Source integrity untrusted |

13 Node cases passed over real HTTP. Independently queried graph: exactly two
Actions (`edit`, `bash`), one expected output digest marked untrusted, no Source text.
Rejected callbacks created no successful Action. Source review confirms argument
fingerprints at core lines 114/634, explicit integer exit zero at 639, requested and
metadata path revalidation at 651, and intended/post-file hash comparison at 660.

No new product defect was demonstrated by these cases. Privacy claims cover the
recorded Pedigree request bodies, not model-provider traffic, arbitrary relative
filenames or all possible secrets embedded in filenames. Shell commands are gated,
not sandboxed; they may access credential files or outside paths. Native file-path
checks and hash equality detect tested inconsistencies, not exclusive authorship
or race-free confinement of the runtime writer. These limitations were documented
already in the native ADR/builder report and remain unresolved boundaries.

## Commands and actual completed results

```powershell
$env:PYTHONPATH=(Join-Path $PWD src)
$env:FALKOR_HOST='127.0.0.1'
$env:FALKOR_PORT='6389'
$env:PEDIGREE_ENV='test'
& $env:QA_PYTHON -m pytest -q tests/security/test_release_independent.py tests/security/test_tenant_db_service.py tests/integration/test_capture_delivery.py tests/integration/test_components.py tests/integration/test_ui_configuration.py tests/unit/test_startup_maintenance.py tests/unit/test_production_launch.py tests/unit/test_capture_spool.py tests/unit/test_claude_hook.py
```

Exit 0: **76 passed in 19.11s**. Includes the original WCC regression, scoped-DB
failure injection and deployment-admin resume tests. This is independent execution
of existing tests, not independent authorship of those tests.

```powershell
& $env:QA_PYTHON -m pytest -q -s tests/security/test_release_round2.py
node --test adapters/opencode/tests/native-tools.test.js
```

Both exit 0: **8 passed in 2.64s** (includes 13 Node attacks; zero failed/skipped),
and builder focused Node suite **16 passed, 0 failed/skipped**. Output excerpts:

```text
REAL DB: exactly edit/bash actions; output digest untrusted; no source text
[fixture-ownership] PASS: session sentinel graph and registry unchanged
```

The installed write/edit/Bash/revoked-read proof in
`docs/qa/opencode-native-local.md` was read and its limits reviewed. It was not
reexecuted as an installed runtime in this review and is not promoted to independent
installed evidence. The focused Node suite separately covers write success,
replaced symlink metadata, gate denial, duplicate callbacks, malformed/truncated
results, bounds and failed delivery.

```powershell
$env:INDEPENDENT_QA_CONTAINER='pedigree-round2-6389'
& $env:QA_PYTHON tests/security/release_runtime_probe.py
```

Exit 0, with real process/HTTP/database output:

```text
EMPTY: module 42201; zero tenants; no mounted volumes
PRODUCTION: ready=200; tenants=[]; demo=false; docs=false/404
API RESTART: same persisted receipt acknowledged
DB RESTART: persisted source/receipt; ACL reprovisioned; exact replay; one source
CLEANUP: owned API stopped; exact synthetic graph/tenant removed
```

The existing probe was narrowly extended to allow the exact owned round-two
container/port mapping and reserve API8119. It asserts the pinned image, no mounts,
port mapping and empty registry before running. It enables AOF/fsync on only this
container, restarts only it, and removes its exact tenant. Graceful same-filesystem
restart is proven, not sudden host failure or backup restore.

## Unresolved objections and handoff

1. Recovery creation/restore, failure injection, rollback and concurrency acceptance
   remain OPEN; inspect the future integrated recovery code in a separate round.
2. Native pending/ack/latch state remains in memory (`pedigree-core.js:444`). The
   separate durable marker work is absent from b33d980. Do not claim restart safety.
3. Native installed evidence in this round remains builder-owned; Claude installed
   acceptance, browser interaction, hosted CI/preview/TestSprite and off-host recovery
   were not independently exercised. No full suite or performance gate is claimed.
4. Documentation still has older summary rows saying ACL/WCC unbuilt and OpenCode
   read-only (handoff lines 43/47/48) despite later release entries. This inherited
   summary drift does not reopen the corrected specific F2/F3 claims, but should be
   reconciled by the integration owner before publication. No product edit made.

Review tests are green on the reviewed implementation. The historical-query red run
is an explicit diagnostic, not a failing test committed into this branch.

## Final hygiene and cleanup

```powershell
& $env:QA_PYTHON -m ruff check .
& $env:QA_PYTHON scripts/secret_scan.py --history
& $env:QA_PYTHON scripts/check_numbers.py
& $env:QA_PYTHON scripts/check_readme.py
git diff --cached --check
```

All exit 0: `All checks passed!`; secret scanner reports no credential shapes in
tracked files or history; numbers check reports 4 files against 70 allowed values;
README check reports 11 headings, links and numbers. Review files were staged for
the scan. Direct virtualenv scanner invocation replaces the shell wrapper's local
`.venv` assumption; no full `make check` result is claimed.

Final independent Db/TenantRegistry query on 6389 printed `MODULE 42201`,
`TENANTS 0`, `GRAPHS ['ped:registry']`. `docker stop pedigree-round2-6389` exited 0.
`Get-NetTCPConnection -LocalPort 8119 -State Listen -ErrorAction SilentlyContinue |
Measure-Object` reported Count 0. The stopped disposable container is retained for
inspection. No original runtime was stopped. Only this report and three review-test
files are included in the review commit; no push.
