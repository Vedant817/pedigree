# E3 fixture ownership independent QA

Verdict: PASS for the targeted local ownership and failure paths. This report does not turn a passing full-suite pytest exit code into proof of data preservation. The previous all-tenant cleanup in E3 was a separate destructive fixture missed by the earlier isolation-fixture-only review. Root reported an actual missing demo tenant; this review did not recreate or inspect any private demo credential.

Scope: tests/evals/test_e3_scenarios.py boundary fixture, its five collected test cases, evals.run_e3.run owned cleanup, and shared DB session ownership guard. Only the new tests/security/test_e3_fixture_ownership_review.py, this report, and explicitly authorized tests/conftest.py were edited by this review. No commits or production edits.

## Commands and actual output

```
.\.venv\Scripts\python.exe -m pytest tests/security/test_e3_fixture_ownership_review.py tests/evals/test_e3_scenarios.py tests/unit/test_fixture_cleanup.py -q -s -rx
.....................[fixture-ownership] PASS: session sentinel graph and registry unchanged
21 passed in 4.23s

.\.venv\Scripts\python.exe -m pytest tests/unit/test_fixture_cleanup.py -q -s
..
2 passed in 0.52s

.\.venv\Scripts\python.exe -m ruff check tests/security/test_e3_fixture_ownership_review.py tests/conftest.py
All checks passed!

.\.venv\Scripts\python.exe scripts/secret_scan.py --history
[secret-scan] PASS: no credential shapes found in tracked files or git history
```

No xfails or skips in the targeted final run. No full suite was run during this follow-up. The unit-only run does not request the shared DB fixture and emits no session sentinel line; this preserves its lazy DB boundary.

## Real DB evidence

All runtime graph checks used local FalkorDB v4.22.1, verified by the shared fixture's pinned module-version check. A separate tiny, uniquely named sentinel tenant and source graph exist BEFORE each reviewed E3 boundary starts. Full source properties and the registry record are compared after scenario execution and fixture teardown. The review tracks successful creates through that invocation's registry instance and verifies those exact graph names and registry IDs are absent afterward. Every outer sentinel is cleaned only by its own exact ID in finally.

Adversarial/ownership cases:

1. Invoke original S1 replay test while unrelated sentinel exists; owned graph/row gone and sentinel unchanged.
2. Invoke original S8 replay test under same boundary checks.
3. Invoke original all-scenarios replay test under same boundary checks.
4. Invoke original scenario gate expectations test under same boundary checks.
5. Invoke original revoked high-risk push gate test under same boundary checks.
6. Throw RuntimeError into the boundary fixture body; real TestClient lifespan portal is released, lifespan task completes, sentinel preserved.
7. Throw AssertionError into the boundary fixture body; same lifecycle/preservation checks.
8. Inject replay exception in single-scenario test; exact owned tenant cleaned and sentinel preserved.
9. Inject replay exception in all-scenario runner; exact owned tenant cleaned and sentinel preserved.
10. Inject replay exception in gate-scenario loop; exact owned tenant cleaned and sentinel preserved.
11. Inject replay exception in high-risk push test; exact owned tenant cleaned and sentinel preserved.
12. Inject headers callback exception after successful tenant create; exact created tenant cleaned by repaired runner and sentinel preserved.
13. AST guard scans all fixture functions for the dangerous combination of list_tenants enumeration and deletion calls/query strings; current tree passes.
14. Guard self-test instantiates a nested session fixture, deletes only that self-test's newly created sentinel graph, verifies the session guard raises the expected ownership assertion, and verifies its exact registry row is still cleaned. The outer unrelated sentinel survives.

TestClient context exit runs Starlette lifespan cleanup but does not set inherited httpx is_closed. Initial review assertions using is_closed were corrected after inspecting installed TestClient.__exit__; final checks use actual portal teardown and completed lifespan task. This was a test expectation error, not an application defect.

## Session-wide preservation gate

The shared session-scoped db fixture now creates one random tiny registry tenant plus source graph before yielding, discards the one-time token immediately, and records registry/public record, exact nodes/properties and edges/properties. On normal pytest session teardown it asserts all remain unchanged and prints the ownership PASS line. Finally it deletes only its own sentinel graph and exact registry ID, even if preservation assertion fails. Its failure path is independently exercised above. This detects future destructive cleanup in DB runs that request the shared fixture; DB tests bypassing that fixture need another test in the run to activate it. Unit-only runs stay DB-free.

## Broad-cleanup scan

Commands reviewed:
```
rg -n 'list_tenants|list_graphs|drop_graph|\.delete\(|DELETE t|DELETE.*Tenant|GRAPH.DELETE|flushdb|flushall' tests
rg -n 'list_tenants|list_graphs|FLUSH|flush|GRAPH.DELETE|MATCH.*Tenant.*DELETE|MATCH.*DETACH DELETE|MATCH.*DELETE' tests evals
```

Remaining list_tenants occurrences are a read-only assertion in tests/integration/test_demo_qa.py and ownership-spy scaffolding/guard detection. No remaining actual fixture enumerates registry tenants for deletion. list_graphs calls predominantly assert absence, check exact owned graph existence, or verify cleanup. The mutation loop in tests/security/test_whatif_audit_review.py is scoped to its exact freshly owned graph + ':wi:' prefix. ACL mechanism cleanup uses its locally generated exact graph/user list. Registry DELETE queries reviewed use a parameterized exact successful-create tenant ID. No flushdb/flushall execution call found. This is source review evidence; only the explicit sentinel cases above are runtime preservation proof. The static guard recognizes a dangerous structure, not all possible helper indirection or aliases.

## Findings and residual limits

E3 destructive boundary cleanup is repaired: the fixture now owns only the TestClient lifecycle, while scenario tests and run() clean the tenants they successfully create. UUID-based IDs replace deterministic hash IDs to avoid repeat-run collisions. Independent runtime cases above pass.

E3-01 cleanup gap: source review found headers_for(credential) executed before the runner try/finally. Root moved it inside the owned cleanup block before this review executed its retained repro. The repaired runtime test passes; the pre-fix gap is a static finding, not a claimed red runtime reproduction.

Some scenario cleanup blocks still suppress graph-delete errors and delete registry rows before graph deletion. This review exercises scenario-body/replay/header failures, not injected DB cleanup failures in every scenario. The earlier isolation fixture's stronger cleanup error handling is not automatically proof for these separate blocks. No global multi-process ID collision test, no production proof, and no restored-demo claim are made here.
