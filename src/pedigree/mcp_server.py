
"""Model Context Protocol server (F-06): wraps the same engine as HTTP."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .api.registry import TenantRegistry
from .api.routes.engine import AGENT_SAFE_KINDS
from .config import get_settings, graph_name
from .db.client import Db
from .db.schema import ensure_schema, node_count
from .engine.audit import audit_sources
from .engine.blame import blame as run_blame
from .engine.blame import impact as run_impact
from .engine.gate import check_action
from .engine.ingest import corroborate, record_action, record_source, remember
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
                return None, None
            if tenant_id is not None and tenant_id != rec.tenant_id:
                return None, None
            tid = rec.tenant_id
        else:
            if tenant_id is None:
                tenant_id = self.default_tenant_id
            # F-1 (red-team P-016): the tokenless convenience path must present the
            # CONFIGURED default token, and it must resolve to the configured default
            # tenant. The tenant id alone must never authorize, and a wrong
            # PEDIGREE_MCP_TOKEN must not silently "work".
            if not self.default_tenant_id or not self.default_tenant_token:
                return None, None
            if tenant_id != self.default_tenant_id:
                return None, None
            rec = self.registry.resolve(self.default_tenant_token)
            if rec is None or rec.tenant_id != self.default_tenant_id:
                return None, None
            tid = rec.tenant_id
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
                                  id: str | None = None,
                                  conf: list[str] | None = None) -> dict:
            if kind not in AGENT_SAFE_KINDS:
                return {"ok": False, "error": {"code": "invalid_argument",
                                               "message": "this source kind needs the capture channel",
                                               "detail": {"kind": kind, "channel": "POST /v1/events"}}}
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            cap = self.registry.get_record(tid).node_cap
            if node_count(self.db, gname) >= cap:
                return {"ok": False, "error": {"code": "quota_exceeded", "message": "node cap exceeded"}}
            def go():
                # MCP has no operator credential (tools must not accept one), so every source
                # an agent records is untrusted regardless of kind (ADR-008).
                r = record_source(self.db, gname, tid, kind=kind, uri=uri, title=title,
                                  integrity="untrusted", conf=conf, id=id)
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
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            cap = self.registry.get_record(tid).node_cap
            if node_count(self.db, gname) >= cap:
                return {"ok": False, "error": {"code": "quota_exceeded", "message": "node cap exceeded"}}
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
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            cap = self.registry.get_record(tid).node_cap
            if node_count(self.db, gname) >= cap:
                return {"ok": False, "error": {"code": "quota_exceeded", "message": "node cap exceeded"}}
            def go():
                r = record_action(self.db, gname, tid, tool=tool, summary=summary,
                                  relied_on=relied_on or [], decision=decision, effect=effect,
                                  risk=risk, artifacts=artifacts or [], id=id)
                return {"id": r.id, "status": r.status, "low_integrity": r.low_integrity,
                        "warnings": r.warnings}
            return _call(go)

        @srv.tool()
        def pedigree_corroborate(tenant_id: str | None = None, token: str | None = None,
                                 memory_id: str = "", source_id: str = "",
                                 by: str = "agent") -> dict:
            if by != "agent":
                # MCP has no operator credential, so it can only assert agent support;
                # human/scanner authority needs the operator header on the REST route (ADR-008).
                return {"ok": False, "error": {"code": "forbidden",
                                               "message": "trusted attestation needs the operator credential",
                                               "detail": {"by": str(by)[:16]}}}
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: (corroborate(self.db, gname, memory_id, source_id, by="agent"), {"ok": True})[1])

        @srv.tool()
        def pedigree_check_action(token: str | None = None, tool: str = "", summary: str = "",
                                  relied_on: list[str] | None = None, session_id: str | None = None,
                                  effect: str | None = None, risk: str | None = None,
                                  audience: list[str] | None = None, max_depth: int = 12,
                                  record: bool = False) -> dict:
            """Check lineage before an action; unknown dependencies require re-verification.

            Read-only by default. Policy is configured by the service operator.
            """
            tid, gname = self._resolve(token=token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            if record and node_count(self.db, gname) >= self.registry.get_record(tid).node_cap:
                return {"ok": False, "error": {"code": "quota_exceeded", "message": "node cap exceeded"}}
            return _call(lambda: check_action(
                self.db, gname, {"tool": tool, "summary": summary, "effect": effect,
                                 "risk": risk, "audience": audience},
                relied_on=relied_on, session_id=session_id, max_depth=max_depth,
                policy_path=self.settings.pedigree_policy_file, record=record, tenant=tid))

        @srv.tool()
        def pedigree_revoke(tenant_id: str | None = None, token: str | None = None,
                            root_id: str = "", reason: str = "", dry_run: bool = False,
                            kind: str = "revoke") -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: revoke(self.db, gname, tid, root_id=root_id, reason=reason,
                                       dry_run=dry_run, kind=kind))

        @srv.tool()
        def pedigree_reinstate(tenant_id: str | None = None, token: str | None = None,
                               root_id: str = "", dry_run: bool = False) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: reinstate(self.db, gname, tid, root_id=root_id, dry_run=dry_run))

        @srv.tool()
        def pedigree_blame(tenant_id: str | None = None, token: str | None = None,
                           node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: run_blame(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_impact(tenant_id: str | None = None, token: str | None = None,
                            node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: run_impact(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_whatif(tenant_id: str | None = None, token: str | None = None,
                            roots: list[str] | None = None) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: whatif(self.db, gname, tid, roots or [], reason="what-if"))

        @srv.tool()
        def pedigree_audit_sources(tenant_id: str | None = None, token: str | None = None,
                                   limit: int = 50) -> dict:
            tid, gname = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            return _call(lambda: audit_sources(self.db, gname, limit=limit))

        @srv.tool()
        def pedigree_report(tenant_id: str | None = None, token: str | None = None) -> dict:
            tid, gname = self._resolve(tenant_id, token)
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
