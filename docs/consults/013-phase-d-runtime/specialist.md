# DevEx recommendation

Choose A: a non-root API image and a separate pinned FalkorDB service. Keep the
database unpublished in Compose; publish the API on loopback by default. Local
development with a host Python process needs a separately documented loopback DB
mapping. Do not make the judge choose between two undocumented topologies.

## Observed evidence

Read-only commands: `Get-Content Dockerfile`, `Get-Content docker-compose.yml`,
`Get-Content Makefile`, `Get-Content scripts/{entrypoint,start-falkordb,fetch-falkordb,clean_clone_check}.sh`
(expanded individually), `Get-Content scripts/seed_demo.py`, and
`Get-Content src/pedigree/demo.py`.

Actual output: Dockerfile starts `FROM ubuntu:24.04`, installs `.[dev,localdb]`,
and has no `USER`. Compose publishes `6379:6379`; its loopback comment is false.
Entrypoint catches seed failure and continues; its `exec` replaces the shell that
owns the DB cleanup trap. These are poor judge failure signals.

`rg --files tests | rg 'seed|demo'` returned integration demo tests.
`git check-ignore scratch/demo-example.json` returned that exact path.
Seeder reserves credentials with `O_EXCL`, mode `0o600`, and prints only the path;
existing active credentials are preserved. Windows mode bits do not prove an
owner-only ACL. Seed fixtures preflight collisions and refuse missing scenarios.
Image packaging must therefore include `demo/scenarios`, not merely the wheel.

## Minimal runnable contract

Document Compose first: `docker compose up --build`, readiness, UI URL, and a
private file retrieval step. Never put operator tokens in Compose output, QA, or
agent configuration. Persist that file across restarts with ownership matching
the API UID. Fail startup on seed errors; distinguish DB reachability from
successful demo initialization. Public deployment remains optional and unverified.

Linux no-Docker: require Python 3.12, Bash, curl and Redis CLI; create/activate the
venv, install locked dev/localdb dependencies, fetch the pinned module, start on
an explicitly owned port/data directory, verify module 42201, seed, serve. A
supervisor must terminate its exact DB process on signals; do not reuse arbitrary
PONG responders. Document PowerShell commands separately with Docker DB. Mark
macOS unsupported/unverified until a native module path is actually tested.

Acceptance: independent literal README execution in a clean Linux container;
non-root UID and writable private volume; repeated seed/restart stability; missing
scenario/unwritable credential directory/occupied port fail clearly; SIGTERM stops
owned processes; CI uses locked installs and pinned DB, runs checks plus bounded
perf, and records hosted status only after an actual run. Confidence: high on
source defects; new platform/runtime success is not yet tested.
