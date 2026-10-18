"""Authenticated weak-component audit summaries."""
from fastapi import Query, Request

from ...db.client import Trace
from ...engine.components import weak_components
from .. import auth


def register(app):
    @app.get("/v1/audit/components")
    def components(request: Request, limit: int = Query(default=50, ge=1, le=100)):
        auth.authenticate(request)
        auth.admit(request, "read")
        trace = Trace()
        result = weak_components(request.state.db, request.state.graph_name, limit=limit, trace=trace)
        result["trace"] = trace.as_list()
        return result
