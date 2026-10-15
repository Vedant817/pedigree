# Consult 006 - Gate rule 1 ("tainted_ancestor"): literal ancestors vs contained contamination

Trigger: F-11 (gate) implementation; design ambiguity in the authoritative spec that changes
observable behaviour. Raised per docs/04 §4 (algorithm/invariant design).

## The question

docs/01-IDEA.md §6.6, decision rule 1 (verbatim):

> 1. any relied node or ancestor status in `revoked|tainted|quarantined` -> **block** if risk >= medium
>    else **warn** (allow + reason) [`code: tainted_ancestor`].

Two readings of "or ancestor":

- **(A) Literal transitive ancestry.** Collect every transitive ancestor of every relied-on id; if any
  has status `revoked|tainted|quarantined`, warn/block by risk. Consequence: an action relying on a
  `preserved` memory (revoked parent, independently corroborated) or on an `ok` descendant of a
  `preserved` memory is warned/blocked, because the revoked source is still an ancestor.
- **(B) Contained contamination.** `engine/compute.py` already resolves containment into node status
  (`ok`, `preserved`) and `taint_parent` (tainted -> revoked root). The "or ancestor" clause is then
  read as the taint propagation already materialised in the graph: warn/block when the relied node
  itself is `tainted|quarantined`, or (for whose provenance chain) `taint_parent` reaches a revoked
  root. Consequence: a `preserved` node and its `ok` descendants do not trigger the gate.

## Context to weigh

- Product claim: "keep what is independently supported" (docs/01 §1, demo script docs/03 1:30-2:00)
  versus the gate blocking with a path (docs/03 2:00-2:25, `git push` in scenario S1).
- Scenario S8 expectation: two memories from a bad page; one corroborated -> `preserved`; **its
  dependent stays `ok`** (docs/03 line 42-48). Under (A), an action relying on that dependent is
  still warned/blocked.
- The real capture channel feeds a **read window** (conservative over-approximation of everything the
  session read, docs/01 §7.3), so tainted and preserved nodes usually arrive together; under (A) an
  action is blocked whenever any contaminated read exists in the session, even if the relied-on
  memory is preserved.
- Measured eval E3b = gate friction on **benign** work (docs/03 line 12-13): false-block/reverify
  rate on recorded real sessions. Under (A) benign sessions that ever read a file/rule that was later
  revoked get warned/blocked; under (B) only uncontained contamination blocks.
- Security posture: the gate exists to stop actions built on poisoned beliefs. Option (B) relies on
  the corroboration signal being sound (agent/human/scanner-asserted, docs/01 §6.5, §7.1 "capture
  integrity").

## Deliverable (per role file)

Recommendation (A or B, or a precise hybrid), the behaviour table it implies, the risk it accepts,
the smallest test that distinguishes them, and how it interacts with `warn` vs `block` by risk.
