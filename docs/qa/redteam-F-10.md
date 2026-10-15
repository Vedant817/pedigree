# F-10 demo seeder boundary regression review

2026-10-15. **PASS for tested seeder collision, authority and credential repairs.**
No source edits, commits or shared demo tenant mutation by this reviewer.

Read `docs/features/F-10-demo.md`, `src/pedigree/demo.py`,
`scripts/seed_demo.py`, fixture integration tests and independent demo QA tests.
Reran existing `test_demo_qa.py` and `test_demo_seed.py` against real local
FalkorDB through throwaway tenant fixtures; tests remove only their own graphs,
registry records and temporary credential files.

## Command and output

```powershell
.\.venv\Scripts\python.exe -m pytest tests/security/test_ui_boundary.py tests/integration/test_ui_api.py tests/integration/test_demo_qa.py tests/integration/test_demo_seed.py -q -s
```

```text
RESEED support-author change: gate_before=block; gate_after=block
CLI seed: created=11 then 0; token absent stdout/stderr; credential unchanged; git check-ignore exit=0
34 passed in 7.70s
```

This scoped run includes 12 demo cases and 22 UI cases. Full `make check` was
owned by the parent agent concurrently and was not redundantly launched here.

## Verified boundaries

| Case | Observed result |
| --- | --- |
| Existing fixture id with unrelated user content/parents | Conflict; complete before/after node-property snapshot unchanged |
| Existing credential destination | FileExistsError, original file unchanged; tenant credential not issued |
| Revoked registry tenant | Explicit refusal; status stays revoked; no credential file created |
| Revoke both scenarios, reseed three times | No new nodes, original statuses retained; medium S8 dependent allows, high push reverifies, S1 action blocks |
| Change human support to agent then reseed | Gate before=block and after=block; no authority upgrade |
| CLI seed then repeat | created 11 then 0; token absent stdout/stderr; credential bytes unchanged and git-ignored |
| Repeated seed with unrelated existing source | Unrelated source untouched, node count stable, invariants clean |
| S1 manifest after actual revocation | Exact statuses, irreversible effects and deep push blame path match fixture; reseed preserves lifecycle |
| S8 manifest after actual revocation | Exact statuses/invariants; medium edit allows but high irreversible action retains untrusted-influence reverification |
| Invalid tenant | Rejected before database use |
| Fixture identity and disclosure | Disjoint ids, explicit synthetic markers |
| Issued credential reused or absent locally | Existing credential remains valid; local file reused without replacement; missing local file does not trigger token rotation |

Source review confirms all fixture collision checks precede new graph writes on
existing graphs, including type/tenant/content/parents checks. Support creation
uses `ON CREATE SET c.by`, so existing authority is not overwritten during reseed.
Credential file uses exclusive creation before issuing a new tenant token.

## Limits

Fixtures are authored synthetic scenarios, not runtime-captured agent behavior.
`human` support is still a caller assertion pending separated authority in F-13;
these tests prove reseed respects an existing downgrade, not human identity.
Seeder is sequential; concurrent seeding, crash recovery between registry/file
writes, deployment filesystem permissions and remote provider behavior are not
proven. No production or shared demo tenant was reset. Existing repository
secret-scan coverage and final whole-tree acceptance remain the parent's checks.
