"""Bounded tenant graph projection for the static UI; no raw content fields."""
from fastapi import Query, Request, Response

from ...db import queries as Q
from ...db.client import Trace
from .. import auth


def register(app, db):
    @app.get("/v1/graph/view")
    def graph_view(request: Request, response: Response, limit: int = Query(default=500, ge=1, le=1000)):
        auth.authenticate(request)
        auth.admit(request, "read")
        response.headers["Cache-Control"] = "no-store"
        graph = request.state.graph_name
        trace = Trace()
        rows = db.ro_query(graph, Q.Q_UI_NODES, {"limit": limit + 1}, op="ui.nodes", trace=trace).result_set or []
        nodes = [{"id": r[0], "type": next(t for t in r[1] if t != "Node"), "status": r[2],
                  "kind": r[3], "title": r[4], "uri": r[5], "tool": r[6], "low_integrity": bool(r[7])}
                 for r in rows[:limit]]
        ids = [n["id"] for n in nodes]
        edges = db.ro_query(graph, Q.Q_UI_EDGES, {"ids": ids, "limit": 4001}, op="ui.edges", trace=trace).result_set or []
        return {"nodes": nodes, "edges": [{"from": r[0], "to": r[1], "type": r[2]} for r in edges[:4000]],
                "truncated": len(rows) > limit or len(edges) > 4000, "trace": trace.as_list()}
