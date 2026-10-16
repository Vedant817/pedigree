# P-029 independent red-team verification

Scope: timeout bounds; strict bearer syntax; metrics auth; environment-controlled API documentation; tenant ID and cap validation. Reviewer owns only `tests/security/test_p029_hygiene.py` and this report plus `P-029.md`; no production source edits. Real DB fixture pins module version 42201 and checks an unrelated session sentinel.

## Initial observed failures

Command:

```powershell
.venv/Scripts/python.exe -m pytest tests/security/test_p029_hygiene.py -q -s --tb=short
```

Actual output (status assertions only; secret-bearing responses are never printed):

```text
...F......FF...........[fixture-ownership] PASS: session sentinel graph and registry unchanged
FAILED tests/security/test_p029_hygiene.py::test_metrics_rejects_unauthorized_headers[\xe9]
FAILED tests/security/test_p029_hygiene.py::test_production_has_no_alternative_public_docs[/redoc]
FAILED tests/security/test_p029_hygiene.py::test_production_has_no_alternative_public_docs[/openapi.json]
3 failed, 20 passed in 5.30s
```

1. An unauthenticated caller sends raw header byte `0xe9` as `X-Admin-Token`; `/metrics` returns **500**, expected 401. String `hmac.compare_digest` does not accept non-ASCII strings. This is an error-handling defect, not a demonstrated metrics authorization bypass. Generic exception detail exposure is tracked separately in P-021; response details were not printed here.
2. With production settings and public docs disabled, `/docs` is hidden but `/redoc` returns **200**.
3. With those same settings, `/openapi.json` returns **200**, exposing the API schema. No tenant data access demonstrated. The literal `/docs` acceptance is satisfied; a claim that API documentation is disabled would be misleading until all three paths are controlled.

No finding above relies on fixtures that delete unrelated registry rows. Only exact randomly allocated test tenant IDs are cleaned; sentinel preservation passed even with failed assertions. Reported defects immediately to the builder; reviewer made no source fixes.

## Adversarial cases

- Missing/empty/wrong/non-ASCII metrics credentials.
- Blank configured admin secret, including dev environment.
- Correct operator credential accepted; tenant bearer alone rejected for metrics.
- Double-space bearer, trailing-space bearer, tab separator and lowercase scheme rejected; standard bearer accepted.
- Production docs off; explicit public opt-in; dev/test/local defaults.
- Alternate ReDoc and OpenAPI schema routes.
- Traversal, graph delimiter, uppercase, too-short and too-long tenant IDs.
- Negative/zero/over-limit node caps; minimum cap accepted.
- Read/write timeout values -1, 0, 60001 rejected; 1 and 60000 accepted.

## Final independent rerun

Builder fixed the three observed defects: all documentation URLs share the visibility decision; metrics compares UTF-8 bytes; duplicate timeout validator removed. Reviewer did not edit production source.

```powershell
.venv/Scripts/python.exe -m pytest tests/security/test_p029_hygiene.py tests/unit/test_timeout_settings.py -q -s --tb=short
```

Actual output:

```text
...................................[fixture-ownership] PASS: session sentinel graph and registry unchanged

35 passed in 6.04s
```

```powershell
.venv/Scripts/python.exe -m ruff check tests/security/test_p029_hygiene.py
```

```text
All checks passed!
```

Verdict: **PASS for tested P-029 scope**. Initial defects closed by independent rerun. In-process HTTP with real pinned DB; no full-suite, benchmark, deployed transport, external-provider or cross-worker claims.
