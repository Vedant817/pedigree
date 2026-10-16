# P-014 independent red-team evidence

Reviewer: independent `quota_final_attack` agent. Finished 2026-10-16 20:51 IST.
Scope: FIX_PROMPT C2 and consult 009 decision; quota engine, REST creators,
MCP tool dispatch, session/source deduplication and coordination ownership.
Reviewer edited only this report and `tests/security/test_p014_quota_attacks.py`;
no production edits or commits. Root implemented the correction described below.

## Verdict

PASS for the tested P-014 boundary after fixing one reproduced inherited-policy
tenant-binding defect. Final independent run: **13 passed in 8.93s**, exit 0.
This is a focused security result, not a full-suite, performance, dogfood,
network-transport, Redis failover or deployment certification.

## Initial environmental block

Command:

```powershell
.venv/Scripts/python.exe -m pytest tests/security/test_p014_quota_attacks.py -q -s
```

Observed `8 errors in 3.39s`; every error was fixture setup:
`FalkorDB is not reachable - run make start-db first`.
No attack case executed. Root then restarted the existing stopped pinned DB
container; reviewer did not provision/download a second DB or remove historical
graphs. The shared real-DB fixture checks FalkorDB module version **42201**
before executing tests.

## Actual RED and correction

Command:

```powershell
.venv/Scripts/python.exe -m pytest tests/security/test_p014_quota_attacks.py -q -s --tb=short
```

Observed before correction:

```text
.....F....HTTP Request: POST http://testserver/v1/memories "HTTP/1.1 429 Too Many Requests"
.[fixture-ownership] PASS: session sentinel graph and registry unchanged

================================== FAILURES ===================================
________________ test_nested_none_policy_cannot_change_tenant _________________
tests\security\test_p014_quota_attacks.py:142: in test_nested_none_policy_cannot_change_tenant
    with pytest.raises(InvalidArgument):
E   Failed: DID NOT RAISE InvalidArgument
1 failed, 10 passed in 7.87s
```

Attack: enter `admission(db, graph_name(tenant), QuotaPolicy(tenant, 2))`, then call
`remember(guarded, graph, "different", id="foreign", quota=None)`. The inherited
context protected the quota count but skipped the tenant check because that
check depended on explicit `quota` being non-null. The foreign-tenant create
returned without rejection against the real DB. This is an engine nesting
binding failure; the review did not establish that an unmodified public REST or
MCP payload can select that engine tenant argument.

Reported to root immediately; root changed `quota_write` to bind the tenant to
the effective explicit **or inherited** policy before planning or writing.
The regression remains. Static check of the corrected source found
`effective_policy` and its `tenant mismatch` rejection at
`src/pedigree/engine/quota.py:202`.

## Final independent rerun

Commands:

```powershell
.venv/Scripts/python.exe -m ruff check tests/security/test_p014_quota_attacks.py
rg -n 'effective_policy|tenant mismatch' src/pedigree/engine/quota.py
.venv/Scripts/python.exe -m pytest tests/security/test_p014_quota_attacks.py -q -s --tb=short
```

Ruff output: `All checks passed!`.
Final pytest output (after independently confirming the correction):

```text
............HTTP Request: POST http://testserver/v1/memories "HTTP/1.1 429 Too Many Requests"
.[fixture-ownership] PASS: session sentinel graph and registry unchanged

13 passed in 8.93s
```

Exit code was polled to completion: **0**. An earlier post-fix run also returned
`13 passed in 7.33s`; the final result above is the certification evidence.

## Adversarial cases and observed assertions

| Case | Evidence asserted on real DB | Final |
| --- | --- | --- |
| Implicit session ensure at full cap | `/v1/sessions/read` with `ensure=yes` returns 429 and complete node/edge snapshot unchanged | PASS |
| Session plus source plus memory batch | Cap 2 rejects all 3 prospective nodes before mutation; complete snapshot unchanged | PASS |
| Public creator parity and zero-growth edge | At cap, REST sources/memories/actions/sessions/revoke/gate-record and corresponding MCP creators reject; corroboration edge remains allowed; snapshots preserved | PASS |
| Policy-record disappearance | Injected registry lookup failure produces REST 404 and MCP `not_in_graph`, without uncapped create or graph change | PASS |
| Explicit nested policy escalation/tenant change | Raised `InvalidArgument`, unchanged graph, owner released | PASS |
| Inherited `quota=None` foreign tenant | Regression now raises `InvalidArgument` with unchanged graph | PASS |
| Explicit/inherited graph change | Wrong graph rejected before creation, original graph unchanged | PASS |
| Hashed canonical sources and repeated sessions | Upper/lowercase same hash with distinct aliases converges; two session events cost one; aliases work for read; zero-growth retries work at cap; new session rejected without mutation | PASS |
| Hashless source identity | Duplicate URI sources converge; direct retry returns same canonical ID at cap; retry-plus-new-URI batch rejects with unchanged snapshot | PASS |
| Invalid zero cap | Policy rejects zero before acquiring lock; graph remains empty | PASS |
| Ownership replacement | Test replaces the owned Redis value; next real mutation is denied, graph stays empty, replacement value survives cleanup of original owner | PASS |
| Ambiguous response after completed write | Actual DB write executes, injected response failure follows; count is 1, lock PTTL is -1; retry cannot acquire owner and count stays 1 | PASS |
| Separate-process REST versus MCP last slot | Spawned processes race through independent app/server instances; exactly `ok` plus `quota_exceeded`, total count 2 | PASS |

The race uses public REST handler dispatch through FastAPI `TestClient` and
actual MCP server `call_tool` dispatch in **separate spawned processes**, each
with its own `Db`; it does not claim socket-level HTTP/stdio MCP transport proof.
The graph logic and quota planning are not mocked. Policy lookup disappearance,
owner replacement and response-loss tests deliberately inject orchestration
failures; they are not evidence of an actual network outage, primary failover,
or a still-executing timed-out server query.

Every attack tenant uses a unique reviewer-owned ID. Cleanup deletes only its
exact graph, registry row and exact quota mutex. Spawned workers are joined
(or terminated then joined) before the fixture removes the mutex. The separate
session-owned sentinel graph and registry record were verified unchanged.
No tokens are printed; fixture credential representations are masked.

## Supported concurrency and remaining limits

Results support consult 009's limited contract: one stable Redis/Falkor primary,
coordination keys protected from eviction/loss, and public creators using the
admission boundary. Mutexes have no expiry; owner-checked release does not delete
a replacement owner's key. Ambiguous mutation failures retain ownership and
fail closed, sacrificing availability. Recovery requires all writers stopped
and DB work quiescent before an operator removes the exact tenant key.
Redis restart/failover/key loss with live writers is outside this proof.

Quota rejection snapshots show no partial writes. Sequential event ingestion
is not a transaction for unrelated invalid-input or DB failures. Trusted direct
engine callers without an explicit or inherited policy remain uncapped by the
documented standalone contract. No additional confirmed public quota bypass was
observed in these cases.
