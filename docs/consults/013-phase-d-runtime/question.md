# Consult 013: Reproducible judge setup and deployment

Context: FIX_PROMPT Phase D (P-003/P-004/P-028). Phase C final root gate is
running; no implementation of Phase D yet. Existing Dockerfile runs Ubuntu as
root, installs dev/localdb dependencies and combines DB/API. Compose publishes DB
on all interfaces despite its loopback comment. No lockfile or CI exists.

Question: What minimal topology and reproducible Linux/no-Docker setup satisfy
the requested python:3.12-slim non-root API, pinned FalkorDB 4.22.1 service,
idempotent synthetic demo and clean-clone CI without exposing operator authority?

Options: A) separate non-root API image and pinned DB compose service, plus
explicit localdb quickstart; B) preserve the current single-container topology.
Recommend one and state seed/token/permissions/health/shutdown failure modes.

Constraints: no new paid services, secrets printed, public deployment or broad
fixture cleanup. Do not touch current Phase C code/docs owned by root. No new
dependencies without this consult. User asks local printed operator token but
also forbids real tokens in QA/logs: use a private ignored credential file and
safe local-only retrieval instructions unless a stronger design is established.
Windows host has Docker with real pinned DB module 42201; no bare macOS host
proof is possible. New setup must use isolated ports/volume/project names.

Evidence to inspect: Dockerfile, docker-compose.yml, pyproject.toml, Makefile,
scripts/{entrypoint,start-falkordb,fetch-falkordb,clean_clone_check}.sh,
scripts/seed_demo.py, src/pedigree/config.py, README.md and SECURITY.md.

Each role writes <=400 words with commands/output, confidence, risks and
acceptance tests: domain.md (verify uncertain external facts and actual pinned
DB behavior in a bounded read-only experiment), architect.md, specialist.md
(DevEx). No source/test changes. Do not print credentials/digests or .env.
