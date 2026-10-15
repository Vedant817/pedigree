# Red-team consult 006 - gate rule 1 (`tainted_ancestor`): reading A vs B

Repro (local FalkorDB v4.22.1, throwaway tenant graph, real engine + real `check_action`; scripts lived in gitignored `scratch/`, deleted after the run): poisoned `rules_file` + `remember(derived_from=[rules], corroborated_by=[attacker-minted file source])` -> `revoke(rules)` -> `check_action(relied_on=[mem])`. Every claim below is measured, not inferred.

## Recommendation

**B, hardened - "contained status + trusted corroboration" (B+).** Rule 1 fires on the *contained* status of the relied node: `revoked|tainted|quarantined` -> **block** if risk >= medium else **warn**. `preserved` passes **only** with trusted corroboration (below); an `ok` descendant of a `preserved` node passes but carries the revoked-ancestor path in `reasons[]`. (A) is rejected: it blocks on ancestry `compute_final` already resolved, breaking S8 ("its dependent stays `ok`") and E3b, and - fatal for a security differentiator - the attacker still gets through by omitting `relied_on` (case 5). Containment is the sound primitive; the corroboration signal is the weak link, so that is what we harden. The shipped WIP gate implements *neither* reading: it checks only the relied node's own status - no ancestor walk, no `taint_parent` walk.

## Attack cases that distinguish A from B

1. **Corroboration laundering (S3 x S8).** Injected prompt, all via MCP: `record_source(kind="rules_file")` (trusted *by kind*, `low_integrity=false`) = poisoned rules file; `record_source(kind="file", uri="docs/launder.md")` = attacker-minted "independent" source; `remember(text="ship with --no-verify", derived_from=[rules], corroborated_by=[fake])`. Human revokes the rules file -> `compute_final` -> `preserved`. *Measured:* `relied_on=[mem]`, `risk=high` -> lineage passes, reason "all dependencies are trusted and healthy"; only the generic irreversibility fallback says `ask`. Relabel `risk=low`, or use `git commit`/`Write` (reversible/medium) -> **allow**. (A): ancestor `src_rules` is `revoked` -> **block**. (B): **allow**. *Gate must:* block/reverify - the sole corroboration is agent-asserted (`c.by='agent'`, verified) against a source the attacker minted itself.
2. **`ok` descendant of a laundered `preserved` node.** `remember(derived_from=[mem])` -> `ok`, `low_integrity=false` (verified), so a control inspecting only the relied node's own status sees nothing. (A): block. (B): allow. *Gate must:* propagate a containment basis to descendants, or walk to the revoked root and reverify at risk >= medium.
3. **`by="human"` forgery.** `corroborate(mem, src, by="human")` succeeds from the agent with no proof of humanity (verified) - "trust human/scanner assertions" alone is not a control. (A): block. (B): allow. *Gate must:* treat `by` as an unauthenticated claim; only out-of-band paths may set `human`/`scanner`.
4. **Untrusted corroborator.** `compute_final`'s health test is `s.status == 'ok'` only - it ignores `integrity`/`low_integrity`, so a `web` source corroborates exactly as well as a repo doc. (A): block. (B): allow. *Gate must:* require the corroborating source to be trusted-integrity, not merely status-ok.

**Also (both readings - and what makes (A) pointless):** (5) `check_action` with `relied_on=[]` while the hook-captured read window holds the tainted memory (verified `read_window -> ['mem_plain']`) -> **allow**, "all dependencies are trusted and healthy"; *must* be `reverify`. (6) `remember`/`record_action` default `via="cite"` (verified), so agent-forged lineage is tagged like a real citation, contradicting docs/01 §9 - any `via`-weighted control is blind. (7) revoke of >50k nodes is async (`202` + poll), so a gate check landing before the barrier sees `ok` - gate reads need the per-tenant revoke lock.

## Compensating controls (what makes B+ defensible)

- **Trusted-only corroboration:** `preserved` passes rule 1 only if some `CORROBORATED_BY` source has `status='ok'` AND `low_integrity=false` AND (`by='scanner'`, or `by='human'` set out-of-band, or (`by='agent'` AND the source is hook-captured and not written by the same session/agent as the memory)); otherwise `preserved` is gated exactly as `tainted`.
- **Containment basis on the node:** store `containment_basis` (`trusted`|`laundered`) in `compute_final`, propagate it to `ok` descendants (kills case 2 with no gate-time ancestor walk), and extend `Q_INV_PRESERVED_WEAK_SUPPORT` to assert it.
- **Warn-vs-block by risk, always with path evidence:** `reasons[{code:'tainted_ancestor', node_id, path:[ids to the revoked root], detail}]`; `warn` (allow + reason) only below medium, `block` at medium and above; never allow silently.
- **Read window as a floor, not a ceiling:** escalates only when `relied_on` is empty (case 5), never blocks on its own - that is what keeps E3b friction low.
- **MCP writes default to `via='agent_reported'`**, `by` downgraded to `agent`, both surfaced in the UI; `not_in_graph` stays `reverify`.

## Exploitability (0 = attacker locked out, 10 = free pass; from the repro above)

| Reading | Poisoned action passes | Benign friction | Evasion | Score |
|---|---|---|---|---|
| (A) literal ancestors | low | **high** - any contaminated read in the session blocks; S8 dependent blocked | omit `relied_on` -> allow | **3** |
| (B) contained | **high** - cases 1-4 all pass | low | relabel risk / omit `relied_on` | **8** |
| (B+) recommended | low - needs a trusted, non-self-minted corroborator | low-medium (`warn` below medium) | needs a genuine second source | **3** |

(A)'s 3 is not a win: it buys security the attacker routes around (case 5) while breaking the product claim and E3b. (B)'s 8 is the number to beat.

## Smallest failing-then-passing test

`tests/security/test_security_F11_gate.py::test_agent_asserted_corroboration_cannot_launder_preserved_past_gate` (`fresh_graph`): `record_source(kind="rules_file", id="src_rules")`; `record_source(kind="file", id="src_fake")`; `remember(derived_from=["src_rules"], corroborated_by=["src_fake"], id="mem")`; `revoke(root_id="src_rules")`; then `check_action(action={"tool":"Bash","summary":"git commit -m x","effect":"reversible","risk":"medium"}, relied_on=["mem"])`.
- **Fails today:** `allow`, "all dependencies are trusted and healthy" (the `git commit` row of the repro) - the laundered `preserved` node clears lineage.
- **Passes after B+:** `block` (risk >= medium) with `reasons[0].code == "tainted_ancestor"` and a `path` ending at `src_rules`. Second assertion in the same test: the `ok` descendant `remember(derived_from=["mem"], id="mem2")` is also not `allow` at medium risk.
