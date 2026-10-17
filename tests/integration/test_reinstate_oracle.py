"""P-012 DB property battery: revoke/reinstate/corroborate sequences against the real FalkorDB
must match the from-scratch global oracle after every recompute (oracle review §3–§5).

Driver contract
  revoke(x)      -> R |= {x}; a CAS flip is a recompute, a repeat revoke is a no-op (not one)
  reinstate(x)   -> R -= {x}; a flip is a recompute, a never-revoked root is a no-op
  corroborate(m,s) -> statuses must be unchanged (lazy, R2); the edge is folded into the model
                      at the next recompute
After a recompute: compare every status against `tests.oracle.global_fixpoint`, assert
`check_invariants == []`, no `quarantined`, `set(db status == 'revoked') == R`, the DERIVED_FROM
edges equal the model, and the structural add-ons (tainted => taint_parent is a bad parent;
ok => taint_parent NULL; preserved => a support source with status ok).

Isolation: one unique tenant per example, dropped in `finally`. The audit repro is the first
explicit `@example`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from pedigree.config import graph_name
from pedigree.db.schema import check_invariants, ensure_schema
from pedigree.engine.ingest import corroborate, record_action, record_source, remember
from pedigree.engine.revoke import reinstate, revoke
from tests.oracle import global_fixpoint

pytestmark = pytest.mark.slow

STATUS_QUERY = (
    "MATCH (n:Node) WHERE n:Source OR n:Memory OR n:Action "
    "RETURN n.id, n.status, n.taint_parent"
)
EDGES_QUERY = "MATCH (c:Node)-[:DERIVED_FROM]->(p:Node) RETURN c.id, p.id"
SUPPORT_QUERY = "MATCH (m:Memory)-[:CORROBORATED_BY]->(s:Source) RETURN m.id, s.id, s.status"


@dataclass(eq=False)
class Scenario:
    """A printable model: nodes/kinds, DERIVED_FROM parents, designated roots, ops."""

    nodes: dict[str, str]
    parents: dict[str, tuple[str, ...]]
    roots: tuple[str, ...]
    ops: tuple[tuple[str, str, str], ...]


AUDIT_REPRO = Scenario(
    nodes={"A": "source", "B": "memory", "Cc": "action"},
    parents={"B": ("A",), "Cc": ("B",)},
    roots=("A", "B"),
    ops=(("revoke", "A", ""), ("revoke", "B", ""), ("reinstate", "A", "")),
)


@st.composite
def scenarios(draw) -> Scenario:
    """1-4 Sources, 3-12 Memories, 0-4 Actions; 2-6 roots with a forced ancestor-descendant
    pair (s0 -> m0, both roots - the audit class); 3-10 ops (40% revoke / 35% reinstate /
    25% corroborate), targets: designated roots 80% / any revocable node 20%."""
    n_s = draw(st.integers(min_value=1, max_value=4))
    n_m = draw(st.integers(min_value=3, max_value=12))
    n_a = draw(st.integers(min_value=0, max_value=4))
    kinds = ["source"] * n_s + ["memory"] * n_m + ["action"] * n_a
    ids = ([f"s{i}" for i in range(n_s)] + [f"m{i}" for i in range(n_m)]
           + [f"a{i}" for i in range(n_a)])
    parents: dict[str, tuple[str, ...]] = {}
    for i, kind in enumerate(kinds):
        if kind == "source":
            parents[ids[i]] = ()
            continue
        k = draw(st.integers(min_value=0, max_value=min(2, i)))
        picks = draw(st.lists(st.integers(min_value=0, max_value=i - 1), min_size=k,
                              max_size=k, unique=True))
        parents[ids[i]] = tuple(sorted(ids[j] for j in picks))
    parents[ids[n_s]] = (ids[0],)  # forced ancestor-descendant root pair
    candidates = ids[: n_s + n_m]
    extras = draw(st.lists(st.integers(min_value=0, max_value=len(candidates) - 1),
                           min_size=0, max_size=4, unique=True))
    roots = tuple(sorted({ids[0], ids[n_s]} | {candidates[j] for j in extras}))
    memories = ids[n_s : n_s + n_m]
    sources = ids[:n_s]
    revocable = candidates
    ops: list[tuple[str, str, str]] = []
    for _ in range(draw(st.integers(min_value=3, max_value=10))):
        roll = draw(st.integers(min_value=0, max_value=99))
        if roll < 40:
            op = "revoke"
        elif roll < 75:
            op = "reinstate"
        else:
            op = "corroborate"
        if op == "corroborate":
            memory = memories[draw(st.integers(min_value=0, max_value=len(memories) - 1))]
            source = sources[draw(st.integers(min_value=0, max_value=len(sources) - 1))]
            ops.append((op, memory, source))
        elif draw(st.integers(min_value=0, max_value=99)) < 80:
            ops.append((op, roots[draw(st.integers(min_value=0, max_value=len(roots) - 1))], ""))
        else:
            ops.append((op, revocable[draw(st.integers(min_value=0, max_value=len(revocable) - 1))], ""))
    return Scenario(nodes=dict(zip(ids, kinds, strict=True)), parents=parents, roots=roots,
                    ops=tuple(ops))


# --- graph I/O --------------------------------------------------------------
def write_scenario(db, gname: str, tenant: str, scenario: Scenario) -> None:
    for node, kind in scenario.nodes.items():
        if kind == "source":
            record_source(db, gname, tenant, kind="web", id=node,
                          uri=f"https://example.invalid/{node}", title=node)
    for node, kind in scenario.nodes.items():  # creation order == the model's index order
        parents = list(scenario.parents.get(node, ()))
        if kind == "memory":
            remember(db, gname, tenant, text=f"text {node}", id=node, derived_from=parents)
        elif kind == "action":
            record_action(db, gname, tenant, tool="bash", summary=node, id=node,
                          relied_on=parents)


def _db_state(db, gname: str) -> dict[str, tuple[str, str | None]]:
    rows = db.ro_query(gname, STATUS_QUERY, {}).result_set or []
    return {r[0]: (r[1], r[2]) for r in rows}


def _db_edges(db, gname: str) -> dict[str, tuple[str, ...]]:
    rows = db.ro_query(gname, EDGES_QUERY, {}).result_set or []
    out: dict[str, list[str]] = {}
    for child, parent in rows:
        out.setdefault(child, []).append(parent)
    return {child: tuple(sorted(ps)) for child, ps in out.items()}


def _db_support(db, gname: str):
    return db.ro_query(gname, SUPPORT_QUERY, {}).result_set or []


# --- failure context --------------------------------------------------------
def _describe(scenario: Scenario) -> str:
    lines = ["scenario:"]
    for node, kind in scenario.nodes.items():
        parents = ", ".join(scenario.parents.get(node, ())) or "(none)"
        lines.append(f"  {node} ({kind}) <- {parents}")
    lines.append(f"  designated roots: {', '.join(scenario.roots)}")
    lines.append("  ops: " + " | ".join(
        f"[{i}] {op}({a}{',' + b if b else ''})" for i, (op, a, b) in enumerate(scenario.ops)))
    return "\n".join(lines)


def _fmt(state: dict) -> str:
    return "{" + ", ".join(f"{k}: {v if not isinstance(v, tuple) else v[0]!r}"
                           for k, v in sorted(state.items())) + "}"


def _cross_check(scenario, expected, state, edges, support_rows, revoked) -> list[str]:
    problems: list[str] = []
    for node in scenario.nodes:
        if node not in state:
            problems.append(f"{node}: missing from the graph")
            continue
        got = state[node][0]
        if got != expected[node]:
            problems.append(f"{node}: expected {expected[node]!r}, db status {got!r} "
                            f"(taint_parent={state[node][1]!r})")
    extra = sorted(set(state) - set(scenario.nodes))
    if extra:
        problems.append(f"nodes in the graph that are not in the model: {extra}")
    actual_revoked = sorted(n for n, (status, _tp) in state.items() if status == "revoked")
    if set(actual_revoked) != set(revoked):
        problems.append(f"db revoked {actual_revoked} != model R {sorted(revoked)}")
    quarantined = sorted(n for n, (status, _tp) in state.items() if status == "quarantined")
    if quarantined:
        problems.append(f"quarantined node(s) after a quiescent op: {quarantined}")
    model_edges = {child: tuple(sorted(ps)) for child, ps in scenario.parents.items() if ps}
    if edges != model_edges:
        problems.append(f"DERIVED_FROM edges differ from the model: db={edges} model={model_edges}")
    healthy = {memory for memory, _source, status in support_rows if status == "ok"}
    for node, want in expected.items():
        taint_parent = state.get(node, (None, None))[1]
        if want == "tainted":
            if taint_parent not in scenario.parents.get(node, ()):
                problems.append(f"tainted {node}: taint_parent {taint_parent!r} is not one of "
                                f"its parents {scenario.parents.get(node, ())}")
            elif state.get(taint_parent, (None, None))[0] not in ("revoked", "tainted"):
                problems.append(f"tainted {node}: taint_parent {taint_parent!r} has status "
                                f"{state.get(taint_parent, (None, None))[0]!r}")
        elif want == "ok" and taint_parent is not None:
            problems.append(f"ok {node} carries taint_parent {taint_parent!r}")
        elif want == "preserved" and node not in healthy:
            problems.append(f"preserved {node} has no corroborating source with status ok "
                            f"(rows: {[r for r in support_rows if r[0] == node]})")
    return problems


def _divergence(index, scenario, op_desc, expected, state, revoked, problems, invariants) -> str:
    lines = [f"P-012 oracle divergence at op[{index}] {op_desc}", _describe(scenario)]
    lines.append("problems:")
    lines.extend(f"  - {p}" for p in problems)
    lines.append("expected (global oracle): " + _fmt(expected))
    lines.append("db statuses:              " + _fmt({k: v[0] for k, v in state.items()}))
    lines.append("db taint_parent:          " + _fmt(
        {k: v[1] for k, v in state.items()}))
    lines.append("expected/actual diff:")
    for node in sorted(expected):
        if expected[node] != state.get(node, (None, None))[0]:
            lines.append(f"  {node}: expected {expected[node]!r}, db "
                         f"{state.get(node, (None, None))[0]!r}")
    lines.append(f"model R = {sorted(revoked)}")
    lines.append("check_invariants: " + (repr(invariants) if invariants else "[]"))
    return "\n".join(lines)


def run_scenario(db, gname: str, tenant: str, scenario: Scenario) -> dict[str, str]:
    """Drive the engine; raise AssertionError with full context at the first divergence."""
    support: dict[str, set[str]] = {}
    pending: list[tuple[str, str]] = []
    revoked: set[str] = set()
    for index, (op, a, b) in enumerate(scenario.ops):
        op_desc = f"{op}({a}{',' + b if b else ''})"
        if op == "corroborate":
            before = _db_state(db, gname)
            corroborate(db, gname, a, b, by="agent")
            state = _db_state(db, gname)
            expected = global_fixpoint(scenario.nodes, scenario.parents, support, revoked)
            problems = _cross_check(scenario, expected, state, _db_edges(db, gname),
                                    _db_support(db, gname), revoked)
            if state != before:
                problems.insert(0, "corroborate changed the status map (R2 says it is lazy): "
                                   f"before={_fmt({k: v[0] for k, v in before.items()})} "
                                   f"after={_fmt({k: v[0] for k, v in state.items()})}")
            if problems:
                raise AssertionError(_divergence(index, scenario, op_desc, expected, state,
                                                 revoked, problems, []))
            pending.append((a, b))
            continue
        if op == "revoke":
            res = revoke(db, gname, tenant, root_id=a, reason="P-012 battery")
            revoked.add(a)
        else:
            res = reinstate(db, gname, tenant, root_id=a)
            revoked.discard(a)
        recomputed = res.get("idempotent") is False
        if recomputed:
            for memory, source in pending:
                support.setdefault(memory, set()).add(source)
            pending.clear()
        state = _db_state(db, gname)
        expected = global_fixpoint(scenario.nodes, scenario.parents, support, revoked)
        problems = _cross_check(scenario, expected, state, _db_edges(db, gname),
                                _db_support(db, gname), revoked)
        invariants = check_invariants(db, gname, expected_tenant=tenant) if recomputed else []
        if invariants:
            problems.insert(0, f"check_invariants at op[{index}]: {invariants}")
        if problems:
            raise AssertionError(_divergence(index, scenario, op_desc, expected, state, revoked,
                                             problems, invariants))
    return {node: status for node, (status, _tp) in _db_state(db, gname).items()}


def _drop(db, gname: str) -> None:
    try:
        db.select(gname).delete()
    except Exception:  # noqa: BLE001 - a missing graph raises
        pass


def _new_tenant(db):
    tenant = "p012" + uuid.uuid4().hex[:12]
    gname = graph_name(tenant)
    ensure_schema(db, gname)
    return tenant, gname


# --- tests ------------------------------------------------------------------
def test_audit_repro_does_not_unrevoke_the_independent_root(db):
    tenant, gname = _new_tenant(db)
    try:
        write_scenario(db, gname, tenant, AUDIT_REPRO)
        final = run_scenario(db, gname, tenant, AUDIT_REPRO)
    finally:
        _drop(db, gname)
    assert final == {"A": "ok", "B": "revoked", "Cc": "tainted"}, final


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(scenarios())
@example(AUDIT_REPRO)
@pytest.mark.timeout(900)
def test_sequences_match_the_global_oracle(db, scenario: Scenario):
    tenant, gname = _new_tenant(db)
    try:
        write_scenario(db, gname, tenant, scenario)
        run_scenario(db, gname, tenant, scenario)
    finally:
        _drop(db, gname)
