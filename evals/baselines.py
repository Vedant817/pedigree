"""Baselines and the Pedigree system for E1 (docs/03 section 2).

Every baseline is a documented *emulation* of the semantics described in public docs/papers,
not the vendor product. Each returns a `Prediction`: the set of nodes the system marks
contaminated, the actions it flags, and the irreversible actions it flags.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from pedigree.engine.compute import compute_final


@dataclass
class Prediction:
    system: str
    pred: set[str] = field(default_factory=set)          # nodes marked contaminated
    preserved: set[str] = field(default_factory=set)     # nodes explicitly kept
    actions: set[str] = field(default_factory=set)       # actions flagged
    irreversible: set[str] = field(default_factory=set)  # flagged irreversible actions


def _closure(dag, root: str) -> set[str]:
    return {n for n in dag.descendants(root) if n != root}


def pedigree(dag) -> Prediction:
    """P - cascade + independent-support preservation, via the engine's real compute_final."""
    members = set(dag.descendants(dag.bad))
    parents = {n: list(dag.parents.get(n, [])) for n in members}
    # independent support: a corroborating source that is not the poisoned root itself
    support = {n: [(s, "ok") for s in dag.support.get(n, [])
                   if s in dag.sources and s != dag.bad] for n in members}
    statuses = {n: "ok" for n in members}
    final = compute_final(members, {dag.bad}, parents, support, statuses)
    pred = {n for n, f in final.items() if f.status == "tainted"}
    preserved = {n for n, f in final.items() if f.status == "preserved"}
    return _with_actions(dag, "P", pred, preserved)


def b2_flat(dag) -> Prediction:
    """B2 - invalidate direct children only."""
    children: set[str] = set()
    for child, ps in dag.parents.items():
        if dag.bad in ps:
            children.add(child)
    return _with_actions(dag, "B2", children, set())


def b1_first_provenance(dag) -> Prediction:
    """B1 - delete items whose *first* provenance is the bad source (Graphiti remove_episode
    semantics): shared/derived items whose first provenance is elsewhere are kept."""
    pred: set[str] = set()
    for node in _closure(dag, dag.bad):
        chain = [node]
        seen = {node}
        cur = node
        while True:
            ps = dag.parents.get(cur, [])
            if not ps:
                break
            cur = ps[0]  # first recorded provenance
            if cur in seen:
                break
            seen.add(cur)
            chain.append(cur)
            if cur == dag.bad:
                pred.update(chain)
                break
            if cur in dag.sources:
                break
    return _with_actions(dag, "B1", pred, set())


def b4_full_cascade(dag) -> Prediction:
    """B4 - full cascade with no support check (PACMI/MemoRepair-style withdraw all descendants)."""
    return _with_actions(dag, "B4", _closure(dag, dag.bad), set())


def b5_time_rewind(dag) -> Prediction:
    """B5 - time-travel rewind: invalidate everything created after the bad source
    (recall 1.0 by construction; it shows the cost, not a method)."""
    order = {nid: i for i, nid in enumerate(dag.created)}
    cut = order[dag.bad]
    pred = {nid for nid in dag.created if order[nid] > cut and nid != dag.bad}
    return _with_actions(dag, "B5", pred, set())


# --- B0: vector-memory delete-by-similarity (TF-IDF cosine) -------------------

def _tfidf_vectors(dag) -> dict[str, dict[str, float]]:
    docs = {nid: dag.texts.get(nid, "").split() for nid in dag.created}
    n_docs = len(docs)
    df: dict[str, int] = {}
    for words in docs.values():
        for w in set(words):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log((n_docs + 1) / (c + 1)) + 1.0 for w, c in df.items()}
    vecs: dict[str, dict[str, float]] = {}
    for nid, words in docs.items():
        if not words:
            vecs[nid] = {}
            continue
        tf: dict[str, float] = {}
        for w in words:
            tf[w] = tf.get(w, 0) + 1
        total = len(words)
        vecs[nid] = {w: (c / total) * idf[w] for w, c in tf.items()}
    return vecs


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(w, 0.0) for w, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def calibrate_b0_theta(dags, lo: float = 0.0, hi: float = 1.0, steps: int = 41) -> tuple[float, list[tuple[float, float]]]:
    """Pick theta maximising F1 over the calibration DAGs (disjoint seeds from evaluation);
    returns (theta, sweep[(theta, f1)])."""
    best_theta, best_f1, sweep = 0.0, -1.0, []
    for i in range(steps):
        theta = lo + (hi - lo) * i / (steps - 1)
        f1s = []
        for dag in dags:
            p = b0_similarity(dag, theta)
            truth_g = _truth_sets(dag)
            f1s.append(_f1(p.pred | p.actions, truth_g))
        mean_f1 = sum(f1s) / len(f1s) if f1s else 0.0
        sweep.append((round(theta, 4), round(mean_f1, 4)))
        if mean_f1 > best_f1:
            best_theta, best_f1 = theta, mean_f1
    return best_theta, sweep


def b0_similarity(dag, theta: float) -> Prediction:
    """B0 - delete items whose TF-IDF cosine to the bad source's text >= theta."""
    vecs = _tfidf_vectors(dag)
    bad_vec = vecs.get(dag.bad, {})
    pred = {nid for nid, v in vecs.items() if nid != dag.bad and _cosine(bad_vec, v) >= theta}
    return _with_actions(dag, "B0", pred, set())


# --- helpers ------------------------------------------------------------------

def _with_actions(dag, system: str, pred: set[str], preserved: set[str]) -> Prediction:
    actions = {a for a in dag.actions if any(m in pred for m in dag.relied_on.get(a, []))}
    irreversible = {a for a in actions if a in dag.irreversible}
    return Prediction(system=system, pred=set(pred), preserved=set(preserved),
                      actions=actions, irreversible=irreversible)


def _truth_sets(dag) -> set[str]:
    from .oracle import truth_for_dag

    return truth_for_dag(dag).G


def _f1(pred: set[str], truth: set[str]) -> float:
    if not pred and not truth:
        return 1.0
    if not pred or not truth:
        return 0.0
    tp = len(pred & truth)
    if tp == 0:
        return 0.0
    precision = tp / len(pred)
    recall = tp / len(truth)
    return 2 * precision * recall / (precision + recall)


SYSTEMS = {
    "P": pedigree,
    "B0": None,  # needs a calibrated theta; built in run_e1
    "B1": b1_first_provenance,
    "B2": b2_flat,
    "B4": b4_full_cascade,
    "B5": b5_time_rewind,
}
