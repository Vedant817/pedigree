# P-015 independent red-team: PASS with explicit status limitation

2026-10-16. Reviewer: delegated `roles_attack`, independent of the implementation.
Scope: stored tenant roles and public REST/MCP capability enforcement from consult
010 / ADR-011. Real local FalkorDB module 42201, actual installed MCP SDK and an
owned Uvicorn TCP subprocess. No paid provider, installed Claude runtime or deployed
service was exercised. No source edits by this reviewer; only the attack test and
this report are owned here. No bearer values appear in this report.

## Commands and actual output

Final command:

```text
.venv/Scripts/python.exe -m pytest tests/security/test_p015_role_attacks.py -q -s --tb=short
................[fixture-ownership] PASS: session sentinel graph and registry unchanged
16 passed in 37.71s
```

```text
.venv/Scripts/python.exe -m ruff check tests/security/test_p015_role_attacks.py
All checks passed!
```

The first attack iteration produced `1 failed, 11 passed in 24.55s` and the same
ownership sentinel PASS. That failure was the reviewer's assumption that any
agent-authored corroboration must leave the graph status `tainted`. The database
returned `preserved` with `by=agent`. The graph algorithm counts descriptive
corroboration regardless of author; the gate separately checks trusted authors.
The follow-up attack added an actual high-risk gate call and observed `block`
(`1 passed in 2.74s`). The final regression explicitly requires both the observed
`preserved`/`agent` row and the blocking gate decision. This is a documented
semantic limitation, not evidence of operator authority or a gate bypass.

## Before and after transcript

Before-fix evidence is builder-provided, not independently rerun by this reviewer:
against commit `303016a` plus the new regression file, the builder ran
`.venv/Scripts/python.exe -m pytest tests/security/test_p015_roles.py -q -s --tb=short`
and recorded `14 failed in 9.20s`. Agent revoke/reinstate returned 200, agent plus
the valid deployment admin header could attest as human, trusted Source creation
returned 200, a late prohibited events claim allowed earlier writes, and the dual
credential fields were absent. This provenance is deliberately separate from the
independent final attack evidence above.

After-fix independent exact inputs, with credentials represented by role names:

1. Operator revokes Source `poison`; dependent Memory `belief` becomes tainted.
   Agent posts `/v1/corroborate` with `memory_id=belief`, `source_id=support`,
   `by=human`, then `by=scanner`, including the valid `X-Admin-Token`: both 403.
   Agent attempts Source `kind=human, integrity=trusted`: 403. The same explicit
   role attacks through `pedigree_corroborate` / `pedigree_record_source` return
   `error.code=forbidden`. Graph node/edge snapshots remain unchanged. High-risk
   `/v1/gate` before and after returns `decision=block`.
2. Agent invokes MCP revoke/reinstate on `poison`: `forbidden`, exact snapshots
   unchanged. Operator MCP human corroboration and revoke succeed; supported
   `belief` becomes `preserved`. Operator REST reinstate succeeds. These positive
   controls establish that the denials are role-specific.
3. Agent creates a Memory using `corroborated_by=[support]` where `support` is an
   existing trusted Source. After operator revoke, graph reports `preserved` and
   edge author `agent`; high-risk gate still blocks. Treat `preserved` as
   descriptive state, never as operator attestation or permission to act.
4. Operator MCP call supplies a different tenant ID: `unauthorized`; original
   graph unchanged. Tenant operator bearer cannot list deployment-wide
   `/admin/tenants` (401). Replacing only the role prefix of a valid agent token
   does not resolve. A real legacy digest resolves as agent and REST revoke is
   forbidden (403).
5. Warm a registry's operator cache, rotate with a genuinely separate
   `python -m pedigree.cli admin issue-operator --id <owned-tenant> --rotate`
   process (stdout captured privately), then reuse the old token: resolver returns
   none and REST returns 401. Replacement resolves as operator; tenant revocation
   invalidates it immediately in the warmed registry and REST also returns 401.
6. Race 12 independent registry objects issuing a missing operator credential,
   four rounds: exactly one successful returned credential per round and it
   resolves. Race 10 independent registry objects creating one tenant, four
   unique owned tenants: exactly one successful credential pair and registry row
   per round, both returned roles resolve. No overwritten successful credential
   or duplicate registry row was observed. These bounded races are evidence for
   the installed DB version, not a proof for arbitrary failover behavior.
7. Agent events batch puts a valid Memory first and a scanner kind / trusted
   integrity / human-author claim last, with the valid admin header: 403 for each
   of three variants; full graph snapshots unchanged.
8. Operator credential configured as MCP default cannot create a Source
   (`unauthorized`). Claude hook `request` with that operator configuration raises
   the content-free role error before network access; graph unchanged. This is
   local hook-code proof, not installed Claude session proof.
9. Through an actual TCP server and installed streamable-HTTP MCP client, invalid
   bearer plus valid operator tool credential, agent-header/operator-tool and
   operator-header/agent-tool conflicts, and duplicate agent/operator headers
   all return `unauthorized`. Ten simultaneous alternating operator/agent
   dry-run calls return successful operator results and forbidden agent results
   with no role leakage; graph snapshots remain unchanged.

## Capability verdict and boundaries

PASS for the tested local P-015 role boundary. No demonstrated agent escalation,
trusted-author laundering, revoked-token reuse, concurrent role leak or public
cross-tenant write bypass remains in these attacks. Enforcement is visible in
`api/auth.py` (`require_operator`, `authorize_source`), whole-batch authorization
in `api/routes/events.py`, matching stored digest/role and live cache rechecks in
`api/registry.py`, and per-call transport context/header conflict handling in
`mcp_server.py`. Issuance's write-first barrier and tenant uniqueness were attacked
using real concurrent calls rather than a mocked query contract.

The descriptive `preserved` status caveat above is material and now disclosed by
the parent in README / KNOWN_ISSUES. Explicit operator MCP calls are permitted by
ADR-011; the domain consult dissented in favor of agent-only MCP. An agent given
an actual operator credential has operator powers by design. This review does
not certify host compromise resistance, arbitrary direct DB callers, O(1) token
lookup, rate limiting (P-020), malformed input/error leakage (P-021), failover,
production deployment, or an installed agent runtime. Full-repository checks are
the parent's separate responsibility.

All graph fixtures own unique IDs; concurrency-created registry rows are removed
by exact ID, transport subprocess is terminated, and the session sentinel
confirms its unrelated graph and registry record were unchanged. No broad graph
or registry cleanup is performed.
