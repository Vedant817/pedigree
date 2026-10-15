# 006 - Gate rule 1 ("tainted_ancestor"): literal ancestors vs contained contamination

**Answer: (B), plus one narrow amendment (1b).** Rule 1 keys on the **materialised status of the relied node**, not on re-walked ancestry: `revoked|tainted|quarantined` -> block if `risk >= medium` else warn; `preserved|ok` -> pass rule 1.
**1b:** a relied node that is `preserved` **and** whose only `CORROBORATED_BY` edges are `by:'agent'` (forgeable, docs/01 §9 "Capture integrity") **and** (`effect='irreversible'` or `risk='high'`) -> **reverify** [`preserved_untrusted_support`], path = node -> `taint_parent` -> revoked root + supporting source.
All else in (A) is rejected: `status` already *is* the join over ancestry, computed by the revoke fixpoint (docs/01 §6.3); re-deriving it at the gate double-counts what the engine resolved and makes `preserved` dead on arrival.

## Evidence actually read

- **PACMI** (arXiv 2610.05732v1 HTML, fetched 2026-10-15): §3 "Validity lattice" orders four states `active < needs-verification < historical-only < superseded`; §4 "Cascading invalidation and repair": "When several paths reach one node, the stronger state in the lattice wins. Unreached nodes remain active."; §4 "Validity-aware retrieval and premise checking": "The premise checker consumes the *inferred graph states*, not merely the retrieved context."
  Downstream consumers read the **propagated state**, not raw ancestry.
- **MAP-Graph** (arXiv 2608.10509v1 HTML, fetched 2026-10-15) §3.4 "Affected Ancestry and Action-Time Gating": "The trust computation labels a memory *affected* when its recursive ancestry contains an untrusted, private, or revoked item. At finalization, bookkeeping propagates this state ... Containment therefore means restricting retrieval or action use while retaining lineage"; gate rule (1) "if a high-risk action has any **affected supporting memory**, return Block"; rule (3) "if a **supporting path** is private, revoked, untrusted, or permission-invalid, return Block, Redact, or Reverify according to risk and cause" (theta 0.30 answer / 0.60 low-medium / 0.85 high).
  §3.3: permission checks "do **not independently traverse every parent record**." Materialised state is primary, the path check a risk-tiered backstop. MAP-Graph has **no** corroboration/declassification concept, so rule (3) is not evidence for (A) here.
- **FIDES** (arXiv 2505.23643v2 HTML, fetched): "By enforcing P-T (but not P-F) we allow any flow as long as it is initiated in a **trusted context**. This corresponds to a form of **robust declassification**." Declassification is a trusted-authority act, never a property of the data or of a second path.
- **Local** docs/research/01-prior-art.md §B rows PACMI / MAP-Graph / CaMeL+FIDES (labels as given there); §D.1 lists "Pre-action gate with Allow/Block/Reverify (MAP-Graph)" as **not novel**. **In-event** competitors/Vaibhaav-Tiwari_lineage.md "Action gate" blocks on `(a:Action)-[:DERIVED_FROM*1..5]->(e:Evidence) WHERE e.stale = true`, and competitors/undograph_DESIGN.md rejects "a reply with a **stale ancestor**" with 409 - both use literal ancestry, and neither has a preserved state (independence there = "not a descendant"). The systems using literal ancestry are exactly the ones with nothing to declassify.
- **Product** docs/01 §6.3, §6.5 ("a 'declassify' is a new Memory with an explicit human source"), §6.6 rule 1, §7.3 read window = "conservative over-approximation"; docs/03 line 48 (S8: "its dependent stays `ok`"), line 59 ("`preserved` is only as good as the corroboration signal"), line 12 (E3b benign friction). Code: `src/pedigree/engine/compute.py:89` sets `taint_parent` on **preserved** nodes too.

## Behaviour table (rule 1 only; rules 2-4 unchanged, applied after)

| relied node status | risk >= medium | risk < medium |
|---|---|---|
| `tainted` / `quarantined` / `revoked` | **block** `tainted_ancestor` | **warn** `tainted_ancestor` |
| `preserved`, corroboration human/scanner | allow (+ info `preserved_lineage`, support shown) | same |
| `preserved`, corroboration agent-only, irreversible or high | **reverify** `preserved_untrusted_support` | same |
| `ok` | allow | allow |

## Why not (A), why not pure (B)

(A) blocks S8's `ok` dependent and every `preserved` node, so the differentiator in docs/01 §1/§4.2 and the demo beat at docs/03 1:30-2:00 is unreachable at the gate; and because the read window over-approximates, any session that ever read a later-revoked file is blocked - E3b friction by construction.
Pure (B) leaves one hole: a revoked **trusted-kind** source (rules-file backdoor, docs/01 §1.1) yields `preserved` with `low_integrity=false`, so rule 3 never fires; 1b closes exactly that hole and nothing more.

## Smallest decisive test

Seed the S8 shape: `R` (Source, `rules_file`, trusted) -> `M1`, `M2`; `M2 -[:CORROBORATED_BY {by:'agent'}]-> D` (Source, `ok`); `M3 -[:DERIVED_FROM]-> M2`. `revoke(R)` -> expect `M1 tainted, M2 preserved, M3 ok`.
Then `check_action(tool='Bash', summary='git push', relied_on=['M3'], risk='medium', effect='reversible')`: (A) returns `block` with `tainted_ancestor`; (B) returns `allow`. Counter-assertion (guards against over-correcting): `relied_on=['M1']` must still `block` under both. One graph, one revoke, two calls.

## Confidence

**V** on code/spec facts (read directly) and on the PACMI/MAP-Graph/FIDES quotes (fetched today); **D** on the in-event notes (README-level only). **U** on whether any published system gates with independent-support preservation - I found none, so this rests on the product's own claims plus the materialised-state pattern.
Prior-art evidence on *this specific question* is **thin**: no cited system has a `preserved` state, so none decides our case.

## Risks / edge cases

- `compute.py:89` writes `taint_parent` on `preserved` nodes while docs/01 §6.3 attributes it to `tainted` only; a gate following `taint_parent` to a revoked root (a naive B) still blocks `M2`. Rule 1 must key on `status` alone; fix the doc/code mismatch either way.
- 1b needs `CORROBORATED_BY.by` at gate time (one extra lookup, only for `preserved` relied nodes).
- `warn` must stay non-blocking (docs/01 §6.6) or E3b friction returns through the back door.
- `src/pedigree/engine/gate.py:104-109` is a stub (blocks on `low_integrity` with no risk tier, no ancestor logic), so this is a design decision, not a regression.

## What would change my mind

Evidence that agent-asserted `CORROBORATED_BY` is reliably forgeable in our capture path (then 1b widens to all `preserved`, or corroboration is restricted to human/scanner at write time); or an E3b measurement showing (B) lets a poisoned belief through an irreversible action that (A) would have caught; or a published system that gates on literal ancestry *while* keeping independently-supported nodes retrievable - that would be direct evidence for (A).
