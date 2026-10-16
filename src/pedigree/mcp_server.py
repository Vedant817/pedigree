
"""Model Context Protocol server (F-06): wraps the same engine as HTTP."""
from __future__ import annotations

import hmac
from contextvars import ContextVar

from mcp.server.mcpserver import MCPServer

from .api.auth import authorize_source
from .api.registry import TenantRegistry
from .config import get_settings, graph_name
from .db.client import Db
from .db.schema import ensure_schema
from .engine.audit import audit_sources
from .engine.blame import blame as run_blame
from .engine.blame import impact as run_impact
from .engine.gate import check_action
from .engine.ingest import corroborate, record_action, record_source, remember
from .engine.quota import QuotaPolicy
from .engine.revoke import reinstate, report, revoke
from .engine.whatif import whatif
from .errors import PedigreeError


def _call(fn, *a, **kw):
    try:
        return {"ok": True, "result": fn(*a, **kw)}
    except PedigreeError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc), "detail": exc.detail}}
    except Exception as exc:
        return {"ok": False, "error": {"code": "internal", "message": str(exc)}}


_UNAUTHORIZED_MSG = "invalid or missing tenant token"
_http_headers: ContextVar[object | None] = ContextVar("pedigree_mcp_http_headers", default=None)


async def _transport_auth_context(ctx, call_next):
    # Installed SDK ServerMiddleware receives the actual per-message HTTP request.
    # ContextVar lifetime includes its async handler/threadpool, never a server field.
    marker = _http_headers.set(getattr(ctx.request, "headers", None))
    try:
        return await call_next(ctx)
    finally:
        _http_headers.reset(marker)


def _forbidden():
    return {"ok": False, "error": {"code": "forbidden", "message": "operator credential required"}}


class PedigreeMCPServer:
    def __init__(self, db=None, settings=None, default_tenant_id=None, default_tenant_token=None):
        self.settings = settings if settings is not None else get_settings()
        self.db = db if db is not None else Db(self.settings)
        self.default_tenant_id = default_tenant_id
        self.default_tenant_token = default_tenant_token
        self.server = MCPServer("pedigree", middleware=[_transport_auth_context])
        self.registry = TenantRegistry(self.db, self.settings)
        self._register_tools()

    def _resolve(self, tenant_id=None, token=None):
        headers = _http_headers.get()
        if headers is not None:
            # A supplied header is authoritative. Even an empty/malformed header
            # must never fall back to tool arguments or configured credentials.
            presented = headers.get("authorization")
            if presented is not None:
                values = headers.getlist("authorization") if hasattr(headers, "getlist") else [presented]
                if len(values) != 1 or not presented.startswith("Bearer "):
                    return None, None, None
                raw = presented[7:]
                if not raw or raw.strip() != raw or any(c.isspace() for c in raw):
                    return None, None, None
                if token is not None and not hmac.compare_digest(raw.encode(), token.encode()):
                    return None, None, None
                token = raw
            elif token is None:
                return None, None, None
        if token is not None:
            rec = self.registry.resolve(token)
            if rec is None or (tenant_id is not None and tenant_id != rec.tenant_id):
                return None, None, None
        else:
            if tenant_id is None:
                tenant_id = self.default_tenant_id
            if not self.default_tenant_id or not self.default_tenant_token:
                return None, None, None
            if tenant_id != self.default_tenant_id:
                return None, None, None
            rec = self.registry.resolve(self.default_tenant_token)
            if rec is None or rec.tenant_id != self.default_tenant_id or rec.role != "agent":
                return None, None, None
        tid = rec.tenant_id
        gname = graph_name(tid)
        ensure_schema(self.db, gname)
        return tid, gname, rec

    def _register_tools(self):
        srv = self.server

        @srv.tool()
        def pedigree_health() -> dict:
            """Health check."""
            return {"ok": True, "ready": self.db.ping(), "module_version": self.db.module_version()}

        @srv.tool()
        def pedigree_record_source(tenant_id: str | None = None, token: str | None = None,
                                  kind: str = "web", uri: str | None = None, title: str | None = None,
                                  id: str | None = None,
                                  conf: list[str] | None = None,
                                  integrity: str | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            def go():
                authorize_source(principal, kind, integrity)
                r = record_source(self.db, gname, tid, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap), kind=kind, uri=uri, title=title,
                                  integrity=integrity if principal.role == "operator" else "untrusted", conf=conf, id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_remember(tenant_id: str | None = None, token: str | None = None, text: str = "",
                              mkind: str = "fact", derived_from: list[str] | None = None,
                              corroborated_by: list[str] | None = None, artifact: str | None = None,
                              artifact_key: str | None = None, id: str | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            def go():
                r = remember(self.db, gname, tid, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap), text=text, mkind=mkind, derived_from=derived_from or [],
                            corroborated_by=corroborated_by or [], artifact=artifact,
                            artifact_key=artifact_key, id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_record_action(tenant_id: str | None = None, token: str | None = None,
                                  tool: str = "", summary: str = "", relied_on: list[str] | None = None,
                                  decision: str | None = None, effect: str | None = None,
                                  risk: str | None = None, artifacts: list[str] | None = None,
                                  id: str | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            def go():
                r = record_action(self.db, gname, tid, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap), tool=tool, summary=summary,
                                  relied_on=relied_on or [], decision=decision, effect=effect,
                                  risk=risk, artifacts=artifacts or [], id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_corroborate(tenant_id: str | None = None, token: str | None = None,
                                 memory_id: str = "", source_id: str = "",
                                 by: str = "agent") -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            if by in ("human", "scanner") and principal.role != "operator":
                return _forbidden()
            return _call(lambda: (corroborate(self.db, gname, memory_id, source_id, by=by, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap)), {"ok": True})[1])

        @srv.tool()
        def pedigree_check_action(token: str | None = None, tool: str = "", summary: str = "",
                                  relied_on: list[str] | None = None, session_id: str | None = None,
                                  effect: str | None = None, risk: str | None = None,
                                  audience: list[str] | None = None, max_depth: int = 12,
                                  record: bool = False) -> dict:
            """Check lineage before an action; unknown dependencies require re-verification.

            Read-only by default. Policy is configured by the service operator.
            """
            tid, gname, principal = self._resolve(token=token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: check_action(
                self.db, gname, {"tool": tool, "summary": summary, "effect": effect,
                                 "risk": risk, "audience": audience},
                relied_on=relied_on, session_id=session_id, max_depth=max_depth,
                policy_path=self.settings.pedigree_policy_file, record=record, tenant=tid, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap)))

        @srv.tool()
        def pedigree_revoke(tenant_id: str | None = None, token: str | None = None,
                            root_id: str = "", reason: str = "", dry_run: bool = False,
                            kind: str = "revoke") -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            if principal.role != "operator":
                return _forbidden()
            return _call(lambda: revoke(self.db, gname, tid, root_id=root_id, reason=reason,
                                       dry_run=dry_run, kind=kind, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap)))

        @srv.tool()
        def pedigree_reinstate(tenant_id: str | None = None, token: str | None = None,
                               root_id: str = "", dry_run: bool = False) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            if principal.role != "operator":
                return _forbidden()
            return _call(lambda: reinstate(self.db, gname, tid, root_id=root_id, dry_run=dry_run, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap)))

        @srv.tool()
        def pedigree_blame(tenant_id: str | None = None, token: str | None = None,
                           node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: run_blame(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_impact(tenant_id: str | None = None, token: str | None = None,
                            node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: run_impact(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_whatif(tenant_id: str | None = None, token: str | None = None,
                            roots: list[str] | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: whatif(self.db, gname, tid, roots or [], reason="what-if"))

        @srv.tool()
        def pedigree_audit_sources(tenant_id: str | None = None, token: str | None = None,
                                   limit: int = 50) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: audit_sources(self.db, gname, limit=limit))

        @srv.tool()
        def pedigree_report(tenant_id: str | None = None, token: str | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: report(self.db, gname))

    def run(self, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8011):
        if transport == "stdio":
            self.server.run(transport="stdio")
        elif transport == "streamable-http":
            self.server.run(transport="streamable-http", host=host, port=port)
        elif transport == "sse":
            self.server.run(transport="sse", host=host, port=port)
        else:
            raise ValueError("unknown transport")


def build_mcp(db=None, settings=None, default_tenant_id=None, default_tenant_token=None):
    return PedigreeMCPServer(db, settings, default_tenant_id, default_tenant_token)
