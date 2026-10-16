# F-18 local red-team review

Attack boundary: local real FalkorDB and isolated test tenants only.

| Finding | Repro/test | Severity | Proposed fix |
|---|---|---|---|
| F18-01 valid singleton source hidden by edgeless PageRank output | test_audit_single_isolated_source_is_reported; real query proves Source status=ok exists, audit returns [] | MEDIUM | Define and implement a bounded edgeless-graph ranking fallback with exact zero reach |
| Older interface table lists status omitted in response | docs/01 section 7.1 versus actual engine result | LOW | Align spec/response and document implemented subset |

Reproduction command: `.\.venv\Scripts\python.exe -m pytest tests/security/test_whatif_audit_review.py -q -rx -s`.
Before fixes: `26 passed, 4 xfailed in 5.23s` (includes F17 tests). Credential mismatch, foreign graph isolation, four malformed limits, four numeric bounds, empty graph, revoked source, shared descendant and isolated source were attempted. All except singleton source passed. See F-18.md for exact evidence and limitations. Repair verification pending.


## Independent repair verification (final)

Commands re-run after production fixes:
```
.\.venv\Scripts\python.exe -m pytest tests/integration/test_whatif.py tests/integration/test_audit.py tests/security/test_whatif_audit_review.py -q -rx -s
.\.venv\Scripts\python.exe -m ruff check tests/security/test_whatif_audit_review.py tests/integration/test_whatif.py
.\.venv\Scripts\python.exe scripts/secret_scan.py --history
```
Observed output:
```
Observed typed concurrent snapshot failure: what-if snapshot unavailable
45 passed in 7.21s
All checks passed!
[secret-scan] PASS: no credential shapes found in tracked files or git history
```
The scanner PASS was from the preceding post-fix run (44 passed before the final extra lost-response regression); the last change added only that review test. All four original expected-failure regressions now pass with no xfail markers. The retained tests proved the defects before repair and now guard the expected behavior.

F18-01 resolved locally: singleton status=ok source now appears with descendants=0 and pagerank=null when the procedure returns no score. This is an explicit contract amendment: null means algorithm omitted a score, not an invented numeric rank. Connected graph ranking and diamond/shared-descendant exact BFS checks continue passing; revoked sources stay excluded. Two real tenant tokens cannot see or simulate the other tenant's foreign-only source.

Final verdict: PASS for tested local implemented subset. The older docs/01 output table still lists status, which current implementation does not return; the feature spec explicitly documents the shipped fields. No production/browser UI, arbitrary graph corruption, or huge-graph resource-exhaustion claim. WCC contamination islands and checkpoint/restore remain UNBUILT.
