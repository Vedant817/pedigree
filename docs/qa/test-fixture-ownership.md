# Isolation test fixture ownership review

Feature: tests/integration/test_isolation_concurrency.py app_client teardown and _mk_tenant ownership tracking. Scope is local fixture safety, not application production authorization. Independent review follows .opencode/agents/qa-senior.md.

The original teardown enumerated registry tenants and could delete pre-existing tenant data. The revised fixture owns only IDs whose create request returned 200; it records ownership before parsing the response token. It no longer enumerates all tenant records for deletion. Tests added solely in tests/security/test_fixture_ownership_review.py; production files and README draft were not edited by this review.

Commands run verbatim:
```
.\.venv\Scripts\python.exe -m pytest tests/security/test_fixture_ownership_review.py tests/unit/test_fixture_cleanup.py -q -rx
.\.venv\Scripts\python.exe -m ruff check tests/security/test_fixture_ownership_review.py
```
Observed excerpts:
```
8 passed, 1 xfailed in 0.78s
All checks passed!
9 passed, 1 xfailed in 0.86s
```
First xfail was FO-01, then repaired; the second run's xfail is FO-02 below. No production/deployed/browser proof is implied.

Real FalkorDB v4.22.1 evidence: test_real_preexisting_graph_and_registry_survive_fixture_teardown creates a uniquely owned sentinel registry record/source graph BEFORE invoking the real fixture, then creates another fixture-owned tenant/source. Actual fixture teardown removes its graph and registry row; sentinel graph, full source properties, and registry record remain unchanged. The outer test deletes exactly its own sentinel in finally. No foreign tenant token or secret is printed.

Adversarial orchestration cases (spies are explicitly distinguished from graph proof):
- No successful tenant creation: no deletion calls, client closed.
- Two successful creates: only those exact graph names and registry IDs deleted; registry enumeration is wired to fail if called.
- HTTP 409 create failure: no ownership acquired, no deletes.
- HTTP 200 with malformed response: ownership retained before JSON parsing fails, successful create still cleaned.
- Missing graph/delete exception: owned registry row still deleted, client closed.
- Exception in test body: owned data cleaned, client closed, body exception propagated.
- Registry delete failure: all owned records attempted and client closed before ExceptionGroup after FO-01 fix.
- Real graph-delete failure: DB graph materializes and remains under injected delete error; review finally removes that exact graph.

Findings:
- FO-01 MEDIUM (repaired and verified): registry DELETE error aborted remaining owned cleanup and skipped client.close. Fix collects cleanup errors, attempts all owned rows, closes, then raises ExceptionGroup. Deterministic spy regression now passes.
- FO-02 MEDIUM (initially pending; now repaired and independently verified below): graph-delete errors are suppressed even when a real owned graph remains. Runtime fault injection retains the actual graph while teardown reports success and drops its registry record. Proposed fix: on delete error verify graph absence; if still present or unprovable, retain/report a cleanup error after attempting remaining owned cleanup and closing the client. Regression test_real_owned_graph_delete_failure_is_reported currently xfails.

Initial verdict before final repair: FAIL for complete cleanup truthfulness until FO-02 repair; PASS for independently tested preservation of pre-existing graph/registry and successful-create ownership boundary. Residual risk: no cross-process tenant-ID collision or graph deletion race test; no claim that spies prove real DB failure semantics. Actual graph failure reproduction and sentinel preservation use the real local DB.


## Final independent verification

FO-02 is repaired: graph-delete failure now checks actual graph absence; if the graph remains, or listing fails so absence cannot be proven, the fixture records cleanup failure, continues attempts on all owned records, closes the client and raises ExceptionGroup. The real DB graph-retention regression now passes with its xfail removed. An additional orchestration spy test makes graph listing fail and verifies both owned records are still attempted and client is closed before the error is reported.

Final commands and output:
```
.\.venv\Scripts\python.exe -m pytest tests/security/test_fixture_ownership_review.py tests/unit/test_fixture_cleanup.py -q -rx
11 passed in 0.83s
.\.venv\Scripts\python.exe -m ruff check tests/security/test_fixture_ownership_review.py
All checks passed!
.\.venv\Scripts\python.exe scripts/secret_scan.py --history
[secret-scan] PASS: no credential shapes found in tracked files or git history
```

Final verdict: PASS for local fixture ownership and the tested cleanup failure handling. All review regressions pass with no xfails. Both real DB tests clean exact owned scopes in finally, including the intentionally retained graph from injected deletion failure. Tests added only in the new security review file; no production edits or commits performed. The earlier residual limitations still apply.
