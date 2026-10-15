from __future__ import annotations

"""Model Context Protocol server (F-06): wraps the same engine as HTTP."""

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from .config import get_settings, graph_name
from .db.client import Db
from .db.schema import ensure_schema
from .engine.blame import blame as run_blame, impact as run_impact
from .engine.ingest import record_action, record_source, remember, corroborate
from .engine.revoke import reinstate, report, revoke
from .api.registry import TenantRegistry
from .errors import PedigreeError


def _call(fn, *a, **kw):
    try:
        return {"ok": True, "result": fn(*a, **kw)}
    except PedigreeError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc), "detail": exc.detail}}
    except Exception as exc:
        return {"ok": False, "error": {"code": "internal", "message": str(exc)}}


class PedigreeMCPServer:
    def __init__(self, db=None, settings=None, default_tenant_id=None, default_tenant_token=None):
        self.settings = settings if settings is not None else get_settings()
        self.db = db if db is not None else Db(self.settings)
        self.default_tenant_id = default_tenant_id
        self.default_tenant_token = default_tenant_token
        self.server = MCPServer("pedigree")
        self.registry = TenantRegistry(self.db, self.settings)
        self._register_tools()

    def _resolve(self, tenant_id=None, token=None):
        if token:
            rec = self.registry.resolve(token)
            if rec is None:
                return None, "invalid token"
            if tenant_id is not None and tenant_id != rec.tenant_id:
                return None, "token/tenant mismatch"
            tid = rec.tenant_id
        else:
            if tenant_id is None:
                tenant_id = self.default_tenant_id
            if not tenant_id:
                return None, "tenant_id required"
            try:
                self.registry.get_record(tenant_id)
            except Exception:
                return None, "unknown tenant"
            tid = tenant_id
        gname = graph_name(tid)
        ensure_schema(self.db, gname)
        return tid, gname

    def _register_tools(self):
        srv = self.server

        @srv.tool()
        def pedigree_health() -> dict:
            """Health check."""
            return {"ok": True, "ready": self.db.ping(), "module_version": self.db.module_version()}

        @srv.tool()
        def pedigree_record_source(tenant_id: str | None = None, token: str | None = None,
                                  kind: str = "web", uri: str | None = None, title: str | None = None,
                                  integrity: str | None = None, id: str | None = None,
                                  conf: list[str] | None = None) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            def go():
                r = record_source(self.db, gname, tid, kind=kind, uri=uri, title=title,
                                  integrity=integrity, conf=conf, id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_remember(tenant_id: str | None = None, token: str | None = None, text: str = "",
                              mkind: str = "fact", derived_from: list[str] | None = None,
                              corroborated_by: list[str] | None = None, artifact: str | None = None,
                              artifact_key: str | None = None, id: str | None = None) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            def go():
                r = remember(self.db, gname, tid, text=text, mkind=mkind, derived_from=derived_from or [],
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
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            def go():
                r = record_action(self.db, gname, tid, tool=tool, summary=summary,
                                  relied_on=relied_on or [], decision=decision, effect=effect,
                                  risk=risk, artifacts=artifacts or [], id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_corroborate(tenant_id: str | None = None, token: str | None = None,
                                memory_id: str = "", source_id: str = "", by: str = "human") -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            return _call(lambda: (corroborate(self.db, gname, memory_id, source_id, by=by), {"ok": True})[1])

        @srv.tool()
        def pedigree_revoke(tenant_id: str | None = None, token: str | None = None,
                            root_id: str = "", reason: str = "", dry_run: bool = False,
                            kind: str = "revoke") -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            return _call(lambda: revoke(self.db, gname, tid, root_id=root_id, reason=reason,
                                       dry_run=dry_run, kind=kind))

        @srv.tool()
        def pedigree_reinstate(tenant_id: str | None = None, token: str | None = None,
                               root_id: str = "", dry_run: bool = False) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            return _call(lambda: reinstate(self.db, gname, tid, root_id=root_id, dry_run=dry_run))

        @srv.tool()
        def pedigree_blame(tenant_id: str | None = None, token: str | None = None,
                           node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            return _call(lambda: run_blame(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_impact(tenant_id: str | None = None, token: str | None = None,
                            node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
            return _call(lambda: run_impact(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_report(tenant_id: str | None = None, token: str | None = None) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": tid}}
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

mcp = None


def _build_default():
    global mcp
    try:
        settings = get_settings()
        db = Db(settings)
        if db.ping():
            mcp = build_mcp(db, settings).server
    except Exception:
        mcp = None


_build_default()