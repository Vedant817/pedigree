# F-11 independent adversarial review

Date: 2026-10-15. Verdict: **PASS for the tested F-11 regressions after repair**.
The initial round failed: **5 failed, 15 passed in 5.05s**. Four findings were
reported to the implementation owner; the ancestry finding has two reproductions.
No production source was edited and no commit was made by this reviewer.

## Scope and environment

Read `.opencode/agents/red-team.md`, `docs/features/F-11-gate.md`, consult 006,
the engine gate, REST schemas/route, MCP server and supporting engine/database code.
Tests use REAL local FalkorDB: the shared fixture checks module version `42201`
(v4.22.1) and fails rather than mocking an unavailable server. REST requests run
through FastAPI `TestClient`; MCP calls run through the registered server tool
dispatcher. These are in-process application contracts, not network transport or
installed Claude host proof. Each test creates an isolated random tenant graph;
the fixture deletes its graph and its own record in `ped:registry` afterwards.

## Findings and fixes verified

| Finding | Reproduction / initial observation | Severity | Repair observed | Test id |
| --- | --- | --- | --- | --- |
| Silent allow at ancestry bound | Rules source -> agent-supported preserved belief -> 2 dependent memories; `git push`, anchor last dependent, `max_depth=1`: HTTP 200, `decision=allow`, empty reasons, hook `allow`. Also reproduced with 13 dependents and default depth 12. | High | One extra frontier level detects incomplete closure; `reverify`, `lineage_truncated`, hook `ask`. | `test_truncated_untrusted_support_never_silently_allows[2-1]` and `[13-12]` |
| Recording discarded missing-dependency verdict | `relied_on=["missing"], record=true`: HTTP 404 `not_in_graph`, replacing the computed reverify response. | Medium | HTTP 200 retains `reverify` and supplies `recording_error`; source returns before writing. | `test_record_missing_dependency_retains_reverify` |
| Partial Action on missing session | `session_id="nonexistent", record=true`: HTTP 404 after Action creation; node count delta +1. | Medium | Session existence checked before write; HTTP 200 contains `recording_error`, node delta 0. Fresh unknown session still follows specified `allow + warning:no_lineage` semantics. | `test_record_unknown_session_does_not_leave_partial_action` |
| MCP accepted invalid risk | MCP `risk="LOW", effect="irreversible", summary="git push"`: `ok=true`, classifier silently fell back to high. REST rejects this enum. | Low | Engine validates enums; MCP `ok=false`, `invalid_argument`. | `test_mcp_invalid_risk_is_rejected` |

Initial exact reproduction command (PowerShell, repository root):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/security/test_F11_adversarial.py -q -s
```

Selected original output (random ids and correlation ids omitted):

```text
TRUNCATION 2 1 200 {"decision":"allow","reasons":[],"checked":1,...,"would_verify":[],"effect":"irreversible","risk":"high"}
TRUNCATION 13 12 200 {"decision":"allow","reasons":[],"checked":1,...,"would_verify":[],"effect":"irreversible","risk":"high"}
RECORD_MISSING 404 {"error":{"code":"not_in_graph","message":"unknown ids","detail":{"missing":["missing"],"n_missing":1},...}}
RECORD_SESSION 404 {"error":{"code":"not_in_graph","message":"session or node not found",...}} node_delta 1
MCP_RISK {'ok': True, 'result': {'decision': 'allow', ... 'effect': 'irreversible', 'risk': 'high'}}
5 failed, 15 passed in 5.05s
```

## Attack inventory (20 cases)

| Attack | Observed final result |
| --- | --- |
| Cypher-shaped id `x') DELETE n //` | HTTP 422 |
| Unicode fullwidth lookalike `ｅvil` | HTTP 422 |
| Id containing newline | HTTP 422 |
| Wildcard id `*` | HTTP 422 |
| 65 relied-on ids | HTTP 422 |
| Request `policy_path=C:/Windows/win.ini` | HTTP 422; request schema excludes policy selection |
| Request `tenant=abc` | HTTP 422 |
| Depth 0 | HTTP 422 |
| Depth 13 | HTTP 422 |
| Nine audience tags | HTTP 422 |
| Summary length 301 | HTTP 422 |
| Unknown dependency without record | HTTP 200, reverify |
| Shallow depth laundering | HTTP 200, reverify, lineage_truncated, ask |
| Default depth laundering with 13 descendants | HTTP 200, reverify, lineage_truncated, ask |
| Unknown dependency with record | HTTP 200, reverify, recording_error |
| Nonexistent session with record | HTTP 200, recording_error; node delta 0 |
| Invalid MCP risk | ok=false, invalid_argument |
| Record at cap 1 with one existing source | Record HTTP 429; read-only check HTTP 200; node count remains 1 |
| Direct preserved belief with default agent corroboration | HTTP 200, block |
| Read-only healthy anchored decision | allow; graph node count unchanged |

## Fresh verification after repairs

Ran the same adversarial command in a new shell against current files:

```text
TRUNCATION 2 1 200 {"decision":"reverify","reasons":[{"code":"lineage_truncated","node_id":"dependent1","path":["dependent1"],"detail":"Ancestry exceeds the depth limit; trusted containment cannot be established"}],...}
TRUNCATION 13 12 200 {"decision":"reverify","reasons":[{"code":"lineage_truncated","node_id":"dependent12","path":["dependent12"],"detail":"Ancestry exceeds the depth limit; trusted containment cannot be established"}],...}
RECORD_MISSING 200 {"decision":"reverify",...,"recording_error":{"code":"not_in_graph","missing":["missing"]}}
RECORD_SESSION 200 {"decision":"allow",...,"recording_error":{"code":"not_in_graph","session_id":"nonexistent"}} node_delta 0
MCP_RISK {'ok': False, 'error': {'code': 'invalid_argument', 'message': 'invalid risk', 'detail': None}}
20 passed in 6.95s
```

Also ran the complete repository **check target**, exactly:

```powershell
make check
```

Output:

```text
.venv/Scripts/python.exe -m ruff check .
All checks passed!
.venv/Scripts/python.exe -m pytest -q -m "not slow"
201 passed in 21.95s
.venv/Scripts/python.exe scripts/secret_scan.py
[secret-scan] PASS: no credential shapes found in tracked files
.venv/Scripts/python.exe scripts/check_numbers.py
[check-numbers] PASS: 1 file(s) checked against 4 allowed values
```

`make check` explicitly excludes `slow` tests; it is not a full slow/evaluation run.
Secret scan reports tracked files only. No tool failure blocked this follow-up.

## Residual limits

- `human` / `scanner` corroboration is an explicit caller assertion. The gate's
  supporting-edge check does not establish separated authority or an attested
  transport; that remains F-13. This review does not claim otherwise.
- The command classifier is a heuristic, not a shell parser or sandbox. Host
  events and explicit risk/effect/audience/dependency inputs remain caller supplied.
- Empty/fresh lineage intentionally allows with `warning:no_lineage`. Bounded
  recent session history cannot establish all historical influence.
- Read-only node-count checks establish no new nodes in these cases; engine
  source inspection corroborates use of read queries. They do not prove concurrent
  revoke/write linearizability, atomic quota enforcement, or all graph property
  immutability under arbitrary faults.
- The repaired record path returns `recording_error` when an Action cannot be
  recorded. A successful gate response alone must not be interpreted as a
  successful audit write; clients must check `action_id` / `recording_error`.
- No new attack techniques were added in this verification-only follow-up.
  Installed Claude hooks, OpenCode runtime behavior, hosted deployment, actual
  shell execution prevention and external transports remain outside this report's
  independent evidence.
