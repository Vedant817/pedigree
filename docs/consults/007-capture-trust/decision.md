# Decision - consult 007 (capture trust: stable Source identity + authority separation)

Date: 2026-10-15 ~23:30 IST. Raised by: orchestrator (F-07/F-13 hardening, PROGRESS next action 1).
Specialists: `domain-researcher` (domain.md), `red-team` (redteam.md, real probes against FalkorDB
v4.22.1), `senior-architect` (architect.md - **role-switch**: the subagent failed three times with
provider errors, so the orchestrator wrote it with its own measured probe, see that file).

## Decision

**Derived identity + structural authority, with the deployment's operator credential as the only
trust-granting path (fail closed).**

1. **Source identity is derived, not asserted.** Exact-match indexes on `Source(uri)` and
   `Source(content_hash)` plus the composite unique constraint `Source(uri, content_hash)`
   (measured expressible on v4.22.1 after the indexes are OPERATIONAL). `record_source` does one
   atomic `MERGE` on `(tenant, uri, content_hash)` - or on `(tenant, uri)` when no hash is given -
   so repeated reads of the same artifact converge on one node (measured: 2 identical MERGEs -> 1
   node, same id) and the same uri with a new hash becomes a new version node, leaving the old hash
   revocable. A caller-supplied `id` names the node at creation only; it can never fork the same
   content into a second node, so revoking one copy cannot be escaped by re-capturing with a new id.
   `POST /v1/events` additionally resolves references *within one batch* through an alias map
   (a capture id may name the node, but identity is the artifact).
2. **Authority is structural: the agent channel can only downgrade.**
   - `POST /v1/sources` and `POST /v1/events` record **untrusted** for an agent token whatever the
     body claims (`integrity`, `kind`, `runtime` are not credentials), and trusted-by-default kinds
     (`file`, `rules_file`, `user_prompt`, `human`) are rejected outright without the operator
     credential (`X-Admin-Token`).
   - `pedigree_record_source` (MCP) always records untrusted - the tool never accepts an operator
     credential.
   - `pedigree_corroborate` accepts only `by="agent"`; `human`/`scanner` are `forbidden`.
   - `POST /v1/corroborate` accepts `by in {human, scanner}` **only** with a matching
     `X-Admin-Token` (the deployment's `PEDIGREE_ADMIN_TOKEN`, constant-time compare).
   Rationale: Biba's *-property (write-up needs authority, write-down is free) and in-toto's "a
   self-asserted field ... should not be trusted for security checks" (domain.md).
3. **The in-process engine keeps the seeded/trusted path.** `record_source` called from the seeder
   or CLI still defaults integrity by kind, so the demo's human-attested sources exist without an
   HTTP credential. A registry `role='human'` tenant token was rejected: on a single host it moves
   "forge a string in a body" to "read a string from a file" (red-team measurement).
4. **Corroboration is write-once-then-upgrade.** `Q_CORROBORATE` keeps an existing `by` unless the
   new value is `human|scanner`, so an agent edge can be upgraded by the operator but never
   downgraded (red-team attack 7). The gate's `TRUSTED_SUPPORT = {human, scanner}` (ADR-007)
   therefore only trusts a value the agent channel cannot produce.

## Consequences

- `POST /v1/corroborate` stays callable by the agent channel and records `by='agent'`; it just can
  no longer claim human authority (403 without the operator credential).
- Captured Sources are untrusted over HTTP, so the gate's `untrusted_influence` rule applies to
  irreversible/high-risk actions built on them - the friction cost is measured later in E3b, and
  the demo/seed path (engine) keeps trusted kinds.
- KNOWN_ISSUES 11 (caller-asserted authority) and 12 (repeated reads minting Source ids) are closed
  for the shipped surface; the residuals (a forged capture payload, a compromised host, hash-less
  re-reads after a hashed one) are documented, not claimed away.
- Recorded as ADR-008. **Reversible:** identity = 2 query constants + 1 DDL; authority = route-level
  gating; no engine algorithm changes (revoke/blame/gate untouched).
