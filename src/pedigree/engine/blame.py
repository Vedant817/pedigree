"""Blame and impact (read-only) — docs/01 §6.4.

No writes happen in here. Every traversal uses parameterised Cypher on FalkorDB's FEEDS mirror.
"""
from __future__ import annotations

import collections

from ..config import LIMITS
from ..db import queries as Q
from ..db.client import Db, Trace, chunks
from ..errors import InvalidArgument, NotFoundInGraph
from .ingest import node_exists


def _norm_depth(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise InvalidArgument("max_depth must be an integer", detail={"got": type(raw).__name__})
    if raw < 1:
        raise InvalidArgument("max_depth must be >= 1", detail={"got": raw})
    return min(raw, LIMITS["depth_max"])


def bfs_paths(
    parents_of: dict[str, list[str]],
    start: str,
    targets: collections.abc.Iterable[str],
    limit: int = 12,
) -> dict[str, list[str] | None]:
    """Pure helper: shortest path `start -> target` by following the (child -> parent) map,
    bounded by `limit`. Returns {target: path_list or None}."""
    target_set = set(targets)
    found: dict[str, list[str] | None] = {t: None for t in target_set}
    q: collections.deque[tuple[str, list[str], int]] = collections.deque([(start, [start], 0)])
    seen: set[str] = {start}
    while q:
        cur, path, d = q.popleft()
        if cur in target_set and found[cur] is None:
            found[cur] = list(path)
        if d >= limit:
            continue
        for p in parents_of.get(cur, []):
            if p not in seen:
                seen.add(p)
                q.append((p, path + [p], d + 1))
    return found


def _describe(db: Db, gname: str, ids, *, trace: Trace | None = None) -> dict[str, dict]:
    if not ids:
        return {}
    out: dict[str, dict] = {}
    for ch in chunks(list(ids)):
        res = db.ro_query(gname, Q.Q_NODE_DETAILS, {"ids": ch}, op="blame.detail", trace=trace)
        for row in res.result_set or []:
            nid, labels, status, low_int, tp, kind = (
                row[0], row[1], row[2], row[3], row[4], row[5]
            )
            type_label = next((label for label in labels or [] if label != "Node"), "Node")
            out[nid] = {
                "id": nid,
                "type": kind or type_label,
                "status": status,
                "low_integrity": bool(low_int),
                "taint_parent": tp,
            }
    return out


def blame(
    db: Db,
    gname: str,
    node_id: str,
    *,
    max_depth: int = 12,
    trace: Trace | None = None,
) -> dict:
    exists, _labels = node_exists(db, gname, node_id, trace)
    if not exists:
        raise NotFoundInGraph("unknown id", detail={"id": node_id})

    depth = _norm_depth(max_depth)

    # --- fast path: taint_parent chain -------------------------------------------
    tp_chain = []
    tp = (db.ro_query(gname, Q.Q_TAINT_PARENT, {"id": node_id}, op="blame.taint", trace=trace)
          .result_set or [])
    tp_chain.append(node_id)
    next_tp = tp[0][0] if tp else None
    seen: set[str] = set()
    while next_tp is not None and next_tp not in seen:
        seen.add(next_tp)
        tp_chain.append(next_tp)
        nxt = (
            db.ro_query(gname, Q.Q_TAINT_PARENT, {"id": next_tp}, op="blame.taint", trace=trace).result_set
            or []
        )
        next_tp = nxt[0][0] if nxt else None
        if next_tp in tp_chain:
            break
    fast_root = tp_chain[-1] if len(tp_chain) > 1 else None

    # --- full ancestry fetch (depth + one extra level for truncation detection) ---
    def fetch(d: int):
        res = db.ro_query(gname, Q.Q_ANCESTORS, {"id": node_id, "depth": d}, op="blame.ancestors", trace=trace)
        ids = [r[0] for r in (res.result_set or [])]
        if ids:
            ereq = db.ro_query(gname, Q.Q_ANCESTOR_EDGES, {"ids": ids + [node_id]},
                               op="blame.edges", trace=trace)
            edges = [
                {"from": r[0], "to": r[1], "rel": r[2], "via": r[3]} for r in (ereq.result_set or [])
            ]
        else:
            edges = []
        return ids, edges

    ids_d, edges_d = fetch(depth)
    ids_plus, _ = fetch(min(depth + 1, 13))
    truncated = len(ids_plus) > len(ids_d)

    # include the node itself
    node_set = set(ids_d) | {node_id}
    # pull edges that originate from the node itself (its direct parents) too
    all_ids_for_edges = list(node_set)
    if all_ids_for_edges:
        ereq = db.ro_query(gname, Q.Q_ANCESTOR_EDGES, {"ids": all_ids_for_edges},
                           op="blame.edges", trace=trace)
        edges_d = [{"from": r[0], "to": r[1], "rel": r[2], "via": r[3]} for r in (ereq.result_set or [])]

    details = _describe(db, gname, node_set, trace=trace)
    parents_of: collections.defaultdict[str, list[str]] = collections.defaultdict(list)
    for e in edges_d:
        parents_of[e["from"]].append(e["to"])

    # candidates: revoked roots / untrusted (low-integrity) nodes in the ancestry
    candidate_roots: set[str] = set()
    for nid, info in details.items():
        if nid == node_id:
            continue
        if info["status"] == "revoked" or info["low_integrity"]:
            candidate_roots.add(nid)

    path_map = bfs_paths(parents_of, node_id, candidate_roots, depth)

    roots_out: list[dict] = []
    for target in sorted(candidate_roots):
        if target not in node_set:
            continue
        info = details.get(target, {"id": target, "type": "Node", "status": ""})
        roots_out.append(
            {
                "id": target,
                "kind": info.get("type", "Node"),
                "status": info.get("status", ""),
                "path": path_map.get(target) or [],
            }
        )

    # supplement via fast-path taint chain (de-dup by id)
    if fast_root and fast_root != node_id and not any(r["id"] == fast_root for r in roots_out):
        info = details.get(fast_root, {"id": fast_root, "type": "Source", "status": "revoked"})
        roots_out.append(
            {
                "id": fast_root,
                "kind": info.get("type", "Source"),
                "status": info.get("status", "revoked"),
                "path": tp_chain,
            }
        )

    node_info = details.get(node_id, {"id": node_id, "type": "Node", "status": "ok"})
    graph_nodes = [
        {"id": nid, "status": info["status"], "low_integrity": info["low_integrity"]}
        for nid, info in details.items()
    ]

    return {
        "node": {"id": node_info["id"], "type": node_info.get("type", "Node"),
                 "status": node_info.get("status", "ok")},
        "roots": roots_out,
        "graph": {"nodes": graph_nodes, "edges": edges_d},
        "truncated": truncated,
    }


def impact(
    db: Db,
    gname: str,
    node_id: str,
    *,
    max_depth: int = 12,
    trace: Trace | None = None,
) -> dict:
    exists, _labels = node_exists(db, gname, node_id, trace)
    if not exists:
        raise NotFoundInGraph("unknown id", detail={"id": node_id})

    depth = _norm_depth(max_depth)

    res = db.ro_query(gname, Q.Q_DESCENDANTS, {"id": node_id, "depth": depth},
                      op="impact.descendants", trace=trace)
    ids = [r[0] for r in (res.result_set or [])]
    res_plus = db.ro_query(gname, Q.Q_DESCENDANTS, {"id": node_id, "depth": min(depth + 1, 13)},
                           op="impact.descendants", trace=trace)
    truncated = len({r[0] for r in (res_plus.result_set or [])}) > len(set(ids))

    details = _describe(db, gname, set(ids), trace=trace)

    action_details: dict[str, dict] = {}
    for ch in chunks(sorted(ids)):
        areq = db.ro_query(gname, Q.Q_ACTION_DETAILS, {"ids": ch}, op="impact.actions", trace=trace)
        for r in areq.result_set or []:
            aid, tool, summary, effect, risk, arts, _status = (r[0], r[1], r[2], r[3], r[4], r[5], r[6])
            action_details[aid] = {
                "id": aid, "tool": tool, "summary": summary, "effect": effect,
                "risk": risk, "artifacts": list(arts or []),
            }

    by_label: collections.Counter[str] = collections.Counter()
    by_status: collections.Counter[str] = collections.Counter()
    for _nid, info in details.items():
        by_label[info.get("type", "Node")] += 1
        by_status[info.get("status", "ok")] += 1

    irreversible = [a for a in action_details.values() if a["effect"] == "irreversible"]

    return {
        "node": {"id": node_id},
        "counts": {"by_label": dict(by_label), "by_status": dict(by_status),
                    "n_total": len(ids)},
        "actions": list(action_details.values()),
        "irreversible": irreversible,
        "truncated": truncated,
    }
