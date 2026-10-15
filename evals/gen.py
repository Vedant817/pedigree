"""Deterministic seeded lineage-DAG generator for E1/E2 (docs/03 section 4).

Pure model - no database. The same model can be written into FalkorDB by
`write_to_falkordb` (used only by the cross-check test, so the in-process evaluation
path is proven equivalent to the real engine rather than assumed).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

WORDS = (
    "agent memory revoke taint source rule file web tool policy cache index graph tenant "
    "session hook capture query model prompt trust label derive support preserve commit push "
    "build test deploy config docs readme license schema invariant edge node cluster shard "
    "latency throughput quota limit backup restore audit report number script"
).split()

UNTRUSTED_KINDS = ("web", "tool_output", "mcp_tool_desc")
TRUSTED_KINDS = ("file", "rules_file", "user_prompt", "human")


@dataclass
class Dag:
    seed: int
    params: dict
    sources: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    #: child id -> parent ids in creation order (memories and actions only; sources have none)
    parents: dict[str, list[str]] = field(default_factory=dict)
    #: memory id -> corroborating source ids (independent support)
    support: dict[str, list[str]] = field(default_factory=dict)
    #: action id -> memory ids it relied on
    relied_on: dict[str, list[str]] = field(default_factory=dict)
    irreversible: set[str] = field(default_factory=set)
    texts: dict[str, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)  # creation order of every node
    bad: str = ""

    def descendants(self, root: str) -> list[str]:
        """All transitive children of `root` (inclusive), by following parents in reverse."""
        children: dict[str, list[str]] = {}
        for child, ps in self.parents.items():
            for p in ps:
                children.setdefault(p, []).append(child)
        seen = {root}
        stack = [root]
        while stack:
            cur = stack.pop()
            for kid in children.get(cur, []):
                if kid not in seen:
                    seen.add(kid)
                    stack.append(kid)
        return sorted(seen)


def _text(rng: random.Random) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(6, 18)))


def _derived_text(parents: list[str], texts: dict[str, str], rng: random.Random) -> str:
    """A child's text mostly inherits its parents' words plus noise, so lexical similarity
    actually tracks lineage (otherwise the B0 vector-store baseline is a straw man).
    Bounded so deep levels stay inside the engine's text limit."""
    words: list[str] = []
    for p in parents:
        words.extend(texts.get(p, "").split())
    keep = int(len(words) * 0.7) if words else 0
    words = words[:keep]
    words.extend(rng.choice(WORDS) for _ in range(rng.randint(2, 6)))
    if not words:
        return _text(rng)
    return " ".join(words[:40])


def generate(seed: int, *, S: int = 20, M: int = 200, L: int = 4, fan_in: int = 2,
             p_corr: float = 0.1, A: int = 40) -> Dag:
    """One seeded DAG. `L` levels of memories, each deriving from the previous level's
    memories and (level 0) from sources; each memory independently corroborated with
    probability `p_corr` by a source that is not one of its parents."""
    rng = random.Random(seed)
    dag = Dag(seed=seed, params={"S": S, "M": M, "L": L, "fan_in": fan_in,
                                 "p_corr": p_corr, "A": A})
    for i in range(S):
        sid = f"s{i}"
        dag.sources.append(sid)
        dag.texts[sid] = _text(rng)
        dag.created.append(sid)

    levels: list[list[str]] = []
    remaining = M
    per_level = max(1, M // max(1, L))
    mid = 0
    for level in range(L):
        count = per_level if level < L - 1 else remaining
        level_ids: list[str] = []
        for _ in range(max(1, count)):
            nid = f"m{mid}"
            mid += 1
            remaining -= 1
            if level == 0:
                pool = dag.sources
            else:
                pool = levels[level - 1]
            k = rng.randint(1, max(1, fan_in))
            ps = rng.sample(pool, min(k, len(pool)))
            dag.parents[nid] = list(ps)
            dag.texts[nid] = _derived_text(ps, dag.texts, rng)
            dag.memories.append(nid)
            dag.created.append(nid)
            level_ids.append(nid)
            if rng.random() < p_corr:
                candidates = [s for s in dag.sources if s not in ps]
                if candidates:
                    dag.support[nid] = [rng.choice(candidates)]
        levels.append(level_ids)

    all_mem = dag.memories
    for i in range(A):
        aid = f"a{i}"
        k = rng.randint(1, 5)
        dag.relied_on[aid] = rng.sample(all_mem, min(k, len(all_mem)))
        dag.parents[aid] = list(dag.relied_on[aid])
        if rng.random() < 0.2:
            dag.irreversible.add(aid)
        dag.texts[aid] = _derived_text(dag.parents.get(aid, []), dag.texts, rng)
        dag.actions.append(aid)
        dag.created.append(aid)

    # the bad source: uniform among sources with at least one descendant
    with_children = [s for s in dag.sources if dag.descendants(s)[1:]]
    if not with_children:  # degenerate (M too small); force one memory under s0
        nid = "m0"
        dag.parents[nid] = ["s0"]
        with_children = ["s0"]
    dag.bad = rng.choice(with_children)
    return dag


def write_to_falkordb(db, gname: str, tenant: str, dag: Dag) -> dict[str, str]:
    """Write a generated DAG through the real engine; returns the id map used for ids."""
    from pedigree.engine.ingest import record_action, record_source, remember

    created: dict[str, str] = {}
    for sid in dag.sources:
        res = record_source(db, gname, tenant, id=sid, kind="web", uri=f"http://eval/{sid}",
                            content_hash=None)
        created[sid] = res.id
    for mid in dag.memories:
        res = remember(db, gname, tenant, id=mid, text=dag.texts[mid],
                       derived_from=dag.parents.get(mid, []),
                       corroborated_by=list(dag.support.get(mid, [])))
        created[mid] = res.id
    for aid in dag.actions:
        effect = "irreversible" if aid in dag.irreversible else "reversible"
        risk = "high" if aid in dag.irreversible else "low"
        res = record_action(db, gname, tenant, tool="Bash", summary=dag.texts[aid][:200],
                            relied_on=dag.relied_on[aid], effect=effect, risk=risk, id=aid)
        created[aid] = res.id
    return created
