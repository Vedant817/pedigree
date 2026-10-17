"""P-012 from-scratch global oracle (pseudocode: docs/consults/008-p012-reinstate/oracle.md §3).

Standard library only - no import from `pedigree`, `src` or `evals`; enforced mechanically by
`tests/unit/test_p012_oracle.py::test_oracle_module_imports_nothing_from_the_product`. It is a
third implementation of the status recurrence: `engine/compute.py` uses Kahn topological order,
`evals/oracle.py` sweeps `members/roots/parents/support/statuses`, and this one sweeps only the
descendants of the active root set `R` with no status input at all. Agreement with
`evals/oracle.ground_truth` is proven by a drift guard on that oracle's valid domain, never
assumed.

Differences from `engine/compute.py` are deliberate and documented:
  * `quarantined` is not a bad parent status here: this oracle models a quiescent graph (R4 of
    the review - after a quiescent op no node may remain quarantined, and a quarantined node in
    the graph is itself a divergence the driver reports).
  * The root set `R` is the only revocation input (R5). A stale `revoked` status is not modelled;
    the driver cross-checks `set(db status == 'revoked') == R` after every recompute.
"""

from __future__ import annotations

_BAD = ("revoked", "tainted")
_REVOCABLE_KINDS = ("source", "memory")


def descendants(parents, roots) -> set[str]:
    """Every node reachable from any root by following parent edges downward (roots included)."""
    children: dict[str, list[str]] = {}
    for child, ps in parents.items():
        for parent in ps:
            children.setdefault(parent, []).append(child)
    seen: set[str] = set(roots)
    stack = list(seen)
    while stack:
        current = stack.pop()
        for kid in children.get(current, ()):
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)
    return seen


def global_fixpoint(nodes, parents, support, roots) -> dict[str, str]:
    """Sweep-to-fixpoint status map for the revoke/reinstate recurrence.

    nodes   : id -> kind in {source, memory, action}
    parents : child id -> parent ids (DERIVED_FROM; DAG by construction)
    support : memory id -> corroborating source ids (CORROBORATED_BY)
    roots   : the active revoked root set R (driver model: revoke adds, reinstate removes)

    Returns id -> {ok, revoked, preserved, tainted}; never emits `quarantined`. R7 precedence:
    (1) `r in R => revoked`, even when `r` is also a descendant of another root;
    (2) a descendant not in R with a parent finally `revoked|tainted` is `preserved` iff some
    support source is not in R, else `tainted`; a `preserved` parent is not bad, so its children
    can be `ok`; (3) nodes outside the descendant union are `ok`.
    """
    kinds = dict(nodes)
    revoked = set(roots)
    missing = sorted(revoked - set(kinds))
    assert not missing, f"R must be a subset of nodes; not in the model: {missing}"
    illegal = sorted(r for r in revoked if kinds[r] not in _REVOCABLE_KINDS)
    assert not illegal, f"only source/memory can be revoked roots; got {illegal}"
    for memory, sources in support.items():
        assert kinds.get(memory) == "memory", f"support key is not a memory: {memory!r}"
        bad_targets = sorted(s for s in sources if kinds.get(s) != "source")
        assert not bad_targets, f"support target is not a source: {bad_targets}"

    desc = descendants(parents, revoked)
    status = {n: "ok" for n in kinds}
    for root in revoked:
        status[root] = "revoked"
    sweep = [n for n in kinds if n in desc and n not in revoked]
    for _ in range(len(kinds) + 1):
        changed = False
        for node in sweep:
            if any(status[p] in _BAD for p in parents.get(node, ())):
                new = "preserved" if any(s not in revoked for s in support.get(node, ())) else "tainted"
            else:
                new = "ok"
            if status[node] != new:
                status[node] = new
                changed = True
        if not changed:
            return status
    raise AssertionError("oracle sweep did not stabilise (parents must describe a DAG)")
