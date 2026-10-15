# Decision - consult 006 (gate rule 1: literal ancestors vs contained contamination)

Date: 2026-10-15 ~21:10 IST. Raised by: orchestrator (F-11 implementation blocker).
Specialists: `senior-architect` (architect.md), `red-team` (redteam.md), `domain-researcher` (domain.md).
All three read the repo; the red team additionally ran the real engine against FalkorDB v4.22.1
(throwaway tenant graphs, scripts deleted) - every number below is measured or quotes a file.

## Decision (unanimous, with hardening)

**Reading B + amendment 1b, hardened to B+.**

1. **Rule 1 keys on the relied node's materialised `status`** (`revoked|tainted|quarantined` ->
   block at risk >= medium, else warn). The gate does **not** re-walk literal ancestry: `compute_final`
   already resolved containment into `status` (docs/01 §6.3: "a node whose only bad parent became
   `preserved` is simply `ok`"). Rationale accepted from the architect: single source of truth; S8
   (`ok` dependent of `preserved`) and the demo's preservation claim stay reachable at the gate; E3b
   benign friction stays near zero because the read window over-approximates; no per-hook BFS
   (`Q_ANCESTORS`, depth 12) on the 10 s PreToolUse budget.
2. **Amendment 1b (domain) + corroboration trust (red team):** a `preserved` node passes rule 1
   **only with trusted support** - a `CORROBORATED_BY` edge whose `by` is `human` or `scanner`
   (out-of-band authority, FIDES "robust declassification initiated in a trusted context"). With
   agent-asserted support only, the node is gated exactly as `tainted` (block at >= medium, warn
   below), code `tainted_ancestor`, detail names the support. Reason: `remember(corroborated_by=...)`
   writes `by='agent'` (`engine/ingest.py:260`) and every MCP caller can assert it, so agent-asserted
   corroboration is forgeable (red-team case 1, measured: laundered `preserved` cleared the gate).
3. **Residual-case closure (red-team case 2):** an `ok` descendant of an untrusted-support
   `preserved` node can carry the contamination without `low_integrity`. The gate closes this at
   decision time for `effect='irreversible'` or `risk='high'` only: it walks the relied node's
   ancestor closure (bounded BFS) for `preserved` nodes with untrusted-only support -> **reverify**
   (`preserved_untrusted_support`) with the path. Below that risk tier the node passes; propagating a
   `containment_basis` property in `compute_final` is tracked as hardening (KNOWN_ISSUES, F-12/F-13).
4. **Read window as a floor (red-team case 5):** `relied_on` empty + a session read window that
   contains a `revoked|tainted|quarantined` node -> **reverify** (`not_in_graph`-style honest
   unknown), never silent `allow`; an empty window stays `allow` + `warning:no_lineage` (docs/01 §6.6
   rule 4, "unanchored actions").
5. **Corroboration authority fix (red-team case 3):** `by` defaults to `agent` at every entry point
   (engine `corroborate`, REST `CorroborateRequest`, MCP `pedigree_corroborate`); only an out-of-band
   caller passes `human`/`scanner`. The agent can no longer arrive at `by='human'` by omission.

## Rejected

- (A) literal transitive ancestry: blocks S8's `ok` dependent and every `preserved` node, maximises
  E3b friction (read window over-approximation), adds a per-hook depth-12 BFS, and the attacker routes
  around it anyway by omitting `relied_on` (red-team case 5, measured `allow` before this decision).
- Hybrid (B + ancestor BFS only for irreversible/high) as a *replacement* for 1b-2: rejected as
  redundant with the support-trust check, but its ancestor walk is retained as the case-2 closure.

## Load-bearing invariant (added to `check_invariants`)

`inv_ok_node_has_no_bad_parent`: after any revocation, no `ok` node has a `DERIVED_FROM` parent with
status `revoked|tainted|quarantined` - this is what makes reading `status` at the gate sound.

## Recorded as ADR-007 in docs/DECISIONS.md. Reversibility: the gate is read-only; reverting to (A)
means adding a BFS per relied id before rule 1 (no schema or engine change).
