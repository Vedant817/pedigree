# F-10: Synthetic demo scenarios and repeatable seeding

Status: done after combined checks. Independent QA: docs/qa/F-10.md PASS;
boundary review: docs/qa/redteam-F-10.md PASS.

## Contract

`make demo` runs `scripts/seed_demo.py`, using the configured FalkorDB connection.
The dedicated tenant defaults to `demo`; `PEDIGREE_DEMO_TENANT` is an explicit
override validated by `validate_tenant`. Existing tenant credentials, data and
revocation state are never reset. Scenario ids are namespaced `demo_s1_*` and
`demo_s8_*`. Existing ids undergo whole-fixture immutable identity and parent-set
preflight before any mutation; unrelated collisions are rejected. Matching ids are skipped,
so rerunning after revocation leaves the
interactive demo's current state intact. No deletion or token rotation occurs.

Versioned JSON scenarios are synthetic authored fixtures, not captured coding
sessions. S1 is source -> summary -> rule -> edit -> commit -> push. S8 has two
memories from a bad page; human-attested trusted documentation supports one,
whose dependent remains ok after revocation. Expected post-revocation manifests
are fixtures, checked against actual engine results in integration tests.
Preservation does not clear inherited low integrity: S8's dependent allows a
reversible medium-risk edit, but still requires reverification for a high-risk
push because its original web source was untrusted.

New tenant credentials are saved to ignored `scratch/demo-<tenant>.json` using
exclusive creation; no token is printed. Existing tenants without locally saved
credentials are seeded without rotating tokens; the command reports the need
to use the previously issued credential. No unauthenticated demo access exists.

## Acceptance and invariants

`tests/integration/test_demo_seed.py`: exact S1/S8 post-revoke statuses,
irreversible push listed, human support permits preserved branch, invariants
green, repeated seed creates no duplicate nodes and preserves revoked state,
unrelated nodes unchanged, invalid tenant rejected, registry credential reuse.
Use actual FalkorDB v4.22.1. Seeder checks invariants before returning success.
Existing corroboration edges retain their author; reseeding never upgrades agent
support to human support. Missing fixture support is created only after preflight.

Security: no raw commands execute, no external sites contacted; example URLs use
reserved `.invalid`. Fixture labels and ids carry no private data. Server
credentials remain local. This feature is not live runtime capture proof.

## Builder evidence (2026-10-15; independent QA still pending)

- Before implementation, scoped pytest failed collection with
  `ModuleNotFoundError: No module named 'pedigree.demo'`.
- Real DB inspection: `python -m pedigree.cli db status` reported reachable
  `127.0.0.1:6379`, graph module `42201`.
- `.venv/Scripts/python.exe -m pytest tests/integration/test_demo_seed.py -q`:
  `6 passed in 0.93s` (exit 0), including exact deep push blame path and post-revoke
  reseeding without lifecycle reset. Scoped Ruff: `All checks passed!` (exit 0).
- `make demo`: created 11 existing 0, synthetic true, scenarios S1/S8,
  invariants pass, tenant demo. Repeat: created 0 existing 11, invariants pass.
- New credential saved under ignored `scratch/demo-demo.json`; `git check-ignore
  scratch/demo-demo.json` returned that path. No credential contents printed.
- Existing scenarios remain unrevoked for interactive use. Tests revoke only
  their isolated temporary tenant graphs and remove them through `fresh_graph`.
- Registry test removes its own temporary registry row; no demo or user records
  are deleted. Seeding is sequential and does not promise concurrent seeder safety.
- S1 Action-to-Action lineage is authored synthetic dependency evidence, not a
  hook-captured artifact hash join or proof of an actual commit/push.
