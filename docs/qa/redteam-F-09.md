# F-09 UI boundary regression review

2026-10-15. **PASS for tested API and static-source boundaries.** No source
changes, commits, browser actions or external targets in this review.

Read the feature spec, `api/routes/workspace.py`, `ui/app.js`, static HTML,
database projection queries and existing UI API tests. Added
`tests/security/test_ui_boundary.py` with real isolated tenant fixtures. Fixtures
delete only their own graph and registry rows. Settings use synthetic secrets,
exclude the local env file and blank provider keys.

## Evidence

Executed in a fresh PowerShell process:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/security/test_ui_boundary.py tests/integration/test_ui_api.py tests/integration/test_demo_qa.py tests/integration/test_demo_seed.py -q -s
.\.venv\Scripts\python.exe -m ruff check tests/security/test_ui_boundary.py
```

Final output:

```text
RESEED support-author change: gate_before=block; gate_after=block
CLI seed: created=11 then 0; token absent stdout/stderr; credential unchanged; git check-ignore exit=0
34 passed in 7.70s
All checks passed!
```

The first test iteration used an incorrect `/styles.css` route and failed with
404. HTML references `/style.css`; the test was corrected, then the whole scoped
command above rerun. This was a test path error, not a product defect.

## Boundary results (20 new cases)

| Case | Result |
| --- | --- |
| Two actual tenant credentials and disjoint persisted nodes | Each response contains its own tenant nodes only |
| Missing Authorization | 401, no own node id in body |
| Invalid bearer | 401, no own node id in body |
| Basic instead of bearer | 401, no own node id in body |
| limit 0 | 422 |
| limit -1 | 422 |
| limit 1001 | 422 |
| limit 1000000 | 422 |
| limit abc | 422 |
| limit 1.5 | 422 |
| limit 1 | One node, truncated true, all edges within returned node set |
| limit 2 | Two nodes, truncated true, all edges within returned node set |
| limit 3 | Three nodes, truncated false, closed edge set |
| limit 1000 | Three existing nodes, truncated false, closed edge set |
| Other tenant/graph query fields and headers | Ignored; token still selects own graph |
| Projection allowlist, memory/summary/private token absence | Exact eight node fields; memory and summary markers absent; `Cache-Control: no-store` |
| Public `/` | 200; synthetic server/tenant credentials absent |
| Public `/app.js` | 200; synthetic server/tenant credentials absent |
| Public `/style.css` | 200; synthetic server/tenant credentials absent |
| Static application rendering/auth patterns | textContent present; HTML insertion/eval/browser storage/console.log sinks absent; no-store/error-on-redirect and epoch guards present |

The existing `test_ui_api.py` also passes. Query inspection confirms static
parameterized node projection and edge query limiting to 4001 before returning
4000; edges require both endpoints in the selected ids. Ordinary data was used;
this is regression testing, not exploit development.

## Limits

Static pattern checks establish source choices, not runtime XSS proof or browser
disconnect/race behavior. This reviewer did not operate the root agent's browser
tab. Browser flow, keyboard/mobile layout and actual visual rendering evidence
belong to that independent browser review. The small fixture verifies node-bound
truncation and closed edges; it does not exercise a graph with more than 4000
edges. Error-response cache headers and high-load/concurrent requests are not
covered. Raw summaries may intentionally appear in authenticated impact evidence;
the exclusion verified here applies to `/v1/graph/view`, as specified.
