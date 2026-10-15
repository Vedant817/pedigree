# Consult 007 - Capture trust boundaries: stable Source identity + authority separation

Trigger: F-07/F-13 hardening (PROGRESS next action 1) - two related trust-boundary changes found by
the F-07 capture audit and by red-team consult 006. Schema/contract changes + security boundary,
so docs/04 §4 requires a consult before implementing.

## Problem 1 - unstable Source identity (node churn, measured)

`record_source` mints a fresh id when the caller does not pass one. `POST /v1/events` maps a local
file read to `Source{kind:file|rules_file, uri, content_hash}` only when no `artifact_key` match
exists, so the *same* file read twice produces two Source nodes (with the same uri), and identical
web content fetched twice produces two `Source`s. Consequences measured in the audit: repeated
unmatched reads create new Source ids (KNOWN_ISSUES 11), revocation has more roots to walk, and
`blame` chains end at whichever copy happens to be revoked.

Open design questions: dedupe key = `uri` only, `uri + content_hash`, `kind + uri`, or an explicit
caller-supplied id only? What happens when the same uri returns different content (a page that
changed) - new Source (version) or update-in-place (losing the old hash)? Does the same rule apply
to `web` sources (untrusted, hashable) as to `file` sources? Is dedupe per tenant graph (yes) and
what is the uniqueness constraint we can express in FalkorDB (index on uri? composite? a lookup
query before merge)? Cost: one extra read on the ingest path, bounded by the chunk/index.

## Problem 2 - authority is caller-asserted (measured, red-team consult 006)

- `corroborate(..., by=...)` accepts `human`/`scanner` from any bearer token holder, i.e. from the
  agent itself. ADR-007 made the *gate* treat only `by in {human, scanner}` as trusted support, so
  an injected prompt can mint trusted support by calling `/v1/corroborate` with `by="human"`
  (verified: MCP `pedigree_corroborate` passes the caller's `by` straight through; the default was
  flipped to `agent` in F-11, but explicit `human` is still forgeable).
- `record_source(integrity="trusted")` accepts an explicit integrity upgrade from any token holder,
  so a `web` source can be recorded as trusted (`low_integrity=false`) by the agent.

Open design questions: where must authority come from instead - a separate credential/role for
human attestation (admin token? a UI-only claim?), a server-side channel (UI session, out-of-band
CLI), or a structural rule (agents may only *downgrade*; upgrades require human/scanner authority)?
Which operations are agent-safe (record_source with default integrity, remember, record_action,
check_action), which need authority (corroborate by=human/scanner, integrity=trusted on an
untrusted-kind source, reinstate, revoke)? How does the UI express "the human asserts this"
without asking the human for a second credential (the human has none beyond the tenant token)?

## Constraints to respect

- docs/01 §6.5: "labels are immutable (a 'declassify' is a new Memory with an explicit human
  source)"; integrity defaults by kind; adapters may override.
- docs/01 §7.1/§8: tenant identity comes from the bearer token only; MCP tools never take a tenant
  argument; no stack traces or tokens in responses.
- No LLM; deterministic only. FalkorDB v4.22.1 pinned; static parameterised Cypher; one atomic
  query per mutation unit; chunk writes <= 2000 ids.
- Everything must stay honest in the README: the human is a solo dev with no extra accounts; the
  demo must be runnable locally with a single token.

## Deliverable (per role file)

Recommendation, the smallest schema/contract change that achieves it, the failure modes it accepts,
and the smallest failing-then-passing test. Read the repo first: `src/pedigree/engine/ingest.py`,
`src/pedigree/api/routes/engine.py`, `src/pedigree/adapters.py`, `src/pedigree/mcp_server.py`,
`src/pedigree/db/queries.py`, `docs/01-IDEA.md` §6.1/§6.5/§7.1/§7.3, ADR-007, KNOWN_ISSUES 11-14.
