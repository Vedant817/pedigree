# Phase C independent final security review

Reviewed 2026-10-17 against the source-stable Phase C implementation, after the
audit-limit compatibility correction. This reviewer did not implement product
code or change tests. Owned changes are this report and review addenda only.

## Final executed result

```powershell
.venv/Scripts/python.exe -m pytest tests/security -q -s --tb=short
```

Observed exit 0:

```text
[indexed-auth] rows=31 median_miss_ms=0.665
[indexed-auth] rows=1001 median_miss_ms=0.783
[fixture-ownership] PASS: session sentinel graph and registry unchanged
414 passed, 1 skipped, 1 xfailed in 125.30s (0:02:05)
```

**PASS for C1-C5's exercised local acceptance and C6's final policy reread.**
There were no unexpected failures. This is not an unqualified all-tests-green
claim: the ACL mechanism skipped without `PEDIGREE_DB_ACL_SECRET`; the existing
strict F-08 watchdog xfailed on the stronger eviction-proof lineage property.
The shipped bounded last-K read window can evict an older revoked influence;
these passes do not establish comprehensive or eviction-proof capture. Neither
non-pass is a disabled C1-C5 acceptance case. The auth figures are this run's warm
local medians, not worst-case latency or production guarantees.

## Contract and adversarial scope

Read FIX_PROMPT C1-C6, consult 012's decision, SECURITY.md, KNOWN_ISSUES and the
P-014/P-015/P-020/P-021/P-029 QA and red-team reports. Spot-checked live authority,
REST authorization/admission ordering, public quota injection, audit clamping,
metrics authorization and docs/error boundaries in source. Existing independent
attack modules were rerun alongside builder security regressions; rerunning a
builder test is additional execution evidence, not independent test authorship.

| Gate | Cases exercised in the final security-suite command |
| --- | --- |
| C1 / P-015 | REST/MCP laundering, agent plus deployment-admin non-elevation, forbidden late batch claims with unchanged graph snapshots, operator positive behavior, legacy/prefix-slot confusion, cross-process rotation/revocation, concurrent issuance, cross-tenant denial and actual HTTP credential precedence. |
| C2 / P-014 | Every public creator at cap, sessions and aliases, zero-growth retries/edges, inherited tenant/graph binding, fail-closed registry lookup, independent-process last-slot contention, replaced lock ownership and committed-write/ambiguous-reply lock retention. |
| C3 / P-021 | Malformed shapes and bad batch tails before writes, control/Unicode input, actual chunked exact byte limit and overflow, REST/MCP exception and chained-cause canaries, malformed SDK protocol input and real stdio recovery. |
| C4 / P-020 | Exact 120/121 write boundary, separate reads, one batch admission, rejected shape/permission budget preservation, destructive dual buckets, indexed live authority, bounded concurrent state, actual TCP shared REST/MCP budgets and peer backoff, forwarding spoof refusal and stdio backoff. |
| C5 / P-029 | Bearer whitespace rejection, graph-name and cap validation, timeout bounds, protected metrics including malformed headers, production docs/ReDoc/OpenAPI denial and explicitly enabled docs. |

The audit compatibility correction preserves F-18's integer clamp to 1..50:
0 and negative integers become 1; oversized integers become 50. The unchanged
`test_whatif_audit_review.py` assertions exercise those cases. Noninteger input
still returns 422 before read admission, now tested with `limit=invalid` in the
P-020 regression. This preserves bounded engine work and does not weaken a test
to accept unbounded queries.

## P-036 final reread

SECURITY.md now links completed P-020 independent QA and red-team evidence instead
of claiming verification is pending. Its batch statement says **structurally
malformed**, consistent with sequential partial writes after other engine/DB
failures. It discloses privileged shared DB connections, stable-primary quota
assumptions, manual recovery and no fencing, fail-open hooks and incomplete
installed-runtime capture, stdio line allocation, per-instance rate resets and
missing production/hosted proof. The reviewed P-020 reports additionally spell
out shared-IP denial and already-in-flight authentication work. The private
disclosure contact is an explicit owner TODO; no monitored address is invented.

No new contradiction was identified in this final reread. A policy-document PASS
does not close the human contact requirement or certify production readiness.

## Limits and ownership

The ACL mechanism test requires the deployment secret and is separate from C1-C5;
the service's per-tenant DB principal wiring remains open regardless of that test.
No secret was provisioned for this review. No paid provider, installed agent
session, deployment, push, broad graph/registry cleanup or historical-data sweep
was performed. Stateful fixtures own exact unique scopes and check the unrelated
session graph/registry sentinel. Root owns full check, dogfood and fresh-clone gates.
