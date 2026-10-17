"""Model Context Protocol server (F-06): wraps the same engine as HTTP."""
from __future__ import annotations

import hmac
import json
from contextvars import ContextVar

import anyio
import mcp_types
from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from starlette.responses import JSONResponse

from .api.auth import authorize_source
from .api.registry import TenantRegistry
from .config import LIMITS, SOURCE_KINDS, get_settings, graph_name
from .db.client import Db
from .db.schema import ensure_schema
from .diagnostics import error_payload, unexpected_error
from .engine.audit import audit_sources
from .engine.blame import blame as run_blame
from .engine.blame import impact as run_impact
from .engine.gate import check_action
from .engine.ingest import corroborate, record_action, record_source, remember
from .engine.quota import QuotaPolicy
from .engine.revoke import reinstate, report, revoke
from .engine.whatif import whatif
from .errors import InvalidArgument, PedigreeError
from .http_boundary import BodySizeMiddleware
from .rate_limit import RateLimiter
from .validation import validate_tool_arguments


def _call(fn, *a, **kw):
    try:
        return {"ok": True, "result": fn(*a, **kw)}
    except PedigreeError as exc:
        return {"ok": False, "error": error_payload(exc)}
    except Exception as exc:
        return {"ok": False, "error": unexpected_error(exc, "mcp_engine")}


def _validate_rpc(message):
    """Validate without rendering SDK exceptions containing caller input."""
    mcp_types.jsonrpc_message_adapter.validate_python(message)
    if not isinstance(message, dict):
        raise ValueError("invalid JSON-RPC message")
    if "method" in message:
        adapter = (mcp_types.client_request_adapter if "id" in message
                   else mcp_types.client_notification_adapter)
        adapter.validate_python(message)


class _RPCBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        # BodySizeMiddleware is installed outside this parser.
        message = await receive()
        if message["type"] != "http.request":
            return
        try:
            _validate_rpc(json.loads(message.get("body", b"")))
        except Exception:
            response = JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC message"}})
            await response(scope, receive, send)
            return
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return message
            return await receive()

        await self.app(scope, replay, send)


class _SafeReadStream:
    """Contain parser exceptions before the SDK runner logs or renders them."""
    def __init__(self, stream, write_stream):
        self.stream = stream
        self.write_stream = write_stream

    def __getattr__(self, name):
        return getattr(self.stream, name)

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def clone(self):
        return _SafeReadStream(self.stream.clone(), self.write_stream)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None

    async def receive(self):
        while True:
            item = await self.stream.receive()
            try:
                if isinstance(item, Exception):
                    raise ValueError("invalid JSON-RPC message")
                _validate_rpc(item.message.model_dump(by_alias=True, exclude_unset=True))
            except Exception:
                # No caller-controlled request ID is echoed for an invalid envelope.
                error = mcp_types.JSONRPCError(jsonrpc="2.0", id=None, error=mcp_types.ErrorData(
                    code=-32600, message="Invalid JSON-RPC message"))
                await self.write_stream.send(SessionMessage(error))
                continue
            return item


class _SafeMCPServer(MCPServer):
    async def run_stdio_async(self):
        # Installed SDK 2.3's public runner has no stream hook. Keep its observed
        # five-line plumbing isolated here; fail closed if that contract changes.
        lowlevel = getattr(self, "_lowlevel_server", None)
        if not callable(getattr(lowlevel, "run", None)) or not callable(
                getattr(lowlevel, "create_initialization_options", None)):
            raise RuntimeError("unsupported MCP stdio runner contract")
        async with stdio_server() as (read_stream, write_stream):
            await lowlevel.run(_SafeReadStream(read_stream, write_stream), write_stream,
                               lowlevel.create_initialization_options())

    async def call_tool(self, name, arguments, context=None):
        try:
            arguments = validate_tool_arguments(name, arguments)
            return await super().call_tool(name, arguments, context)
        except PedigreeError as exc:
            payload = {"ok": False, "error": error_payload(exc)}
        except Exception as exc:
            # SDK wrappers retain the original exception in __cause__. Neither is
            # formatted; diagnostics records class and frame metadata only.
            cause = exc.__cause__
            if isinstance(cause, PedigreeError):
                payload = {"ok": False, "error": error_payload(cause)}
            else:
                payload = {"ok": False, "error": unexpected_error(exc, "mcp_tool")}
        return mcp_types.CallToolResult(content=[mcp_types.TextContent(
            type="text", text=json.dumps(payload))], is_error=True)

    def streamable_http_app(self, **kwargs):
        kwargs["max_request_body_size"] = LIMITS["body_bytes"]
        app = super().streamable_http_app(**kwargs)
        app.add_middleware(_RPCBoundary)
        app.add_middleware(BodySizeMiddleware)
        return app

    def sse_app(self, **kwargs):
        kwargs["max_request_body_size"] = LIMITS["body_bytes"]
        app = super().sse_app(**kwargs)
        app.add_middleware(_RPCBoundary)
        app.add_middleware(BodySizeMiddleware)
        return app


_UNAUTHORIZED_MSG = "invalid or missing tenant token"
_http_headers: ContextVar[object | None] = ContextVar("pedigree_mcp_http_headers", default=None)
_http_peer: ContextVar[str | None] = ContextVar("pedigree_mcp_http_peer", default=None)


async def _transport_auth_context(ctx, call_next):
    # Installed SDK ServerMiddleware receives the actual per-message HTTP request.
    # ContextVar lifetime includes its async handler/threadpool, never a server field.
    marker = _http_headers.set(getattr(ctx.request, "headers", None))
    client = getattr(ctx.request, "client", None)
    peer_marker = _http_peer.set(getattr(client, "host", None))
    try:
        return await call_next(ctx)
    finally:
        _http_headers.reset(marker)
        _http_peer.reset(peer_marker)


def _forbidden():
    return {"ok": False, "error": {"code": "forbidden", "message": "operator credential required"}}


class PedigreeMCPServer:
    def __init__(self, db=None, settings=None, default_tenant_id=None, default_tenant_token=None, *, limiter=None):
        self.settings = settings if settings is not None else get_settings()
        self.db = db if db is not None else Db(self.settings)
        self.default_tenant_id = default_tenant_id
        self.default_tenant_token = default_tenant_token
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.server = _SafeMCPServer("pedigree", middleware=[_transport_auth_context])
        self.registry = TenantRegistry(self.db, self.settings)
        self._register_tools()

    def _resolve(self, tenant_id=None, token=None):
        peer = _http_peer.get() or "local:stdio"
        self.limiter.check_peer(peer)

        def unauthorized():
            self.limiter.failed_auth(peer)
            return None, None, None

        headers = _http_headers.get()
        if headers is not None:
            # A supplied header is authoritative. Even an empty/malformed header
            # must never fall back to tool arguments or configured credentials.
            presented = headers.get("authorization")
            if presented is not None:
                values = headers.getlist("authorization") if hasattr(headers, "getlist") else [presented]
                if len(values) != 1 or not presented.startswith("Bearer "):
                    return unauthorized()
                raw = presented[7:]
                if not raw or raw.strip() != raw or any(c.isspace() for c in raw):
                    return unauthorized()
                if token is not None and not hmac.compare_digest(raw.encode(), token.encode()):
                    return unauthorized()
                token = raw
            elif token is None:
                return unauthorized()
        if token is not None:
            rec = self.registry.resolve(token)
            if rec is None or (tenant_id is not None and tenant_id != rec.tenant_id):
                return unauthorized()
        else:
            if tenant_id is None:
                tenant_id = self.default_tenant_id
            if not self.default_tenant_id or not self.default_tenant_token:
                return unauthorized()
            if tenant_id != self.default_tenant_id:
                return unauthorized()
            rec = self.registry.resolve(self.default_tenant_token)
            if rec is None or rec.tenant_id != self.default_tenant_id or rec.role != "agent":
                return unauthorized()
        tid = rec.tenant_id
        gname = graph_name(tid)
        return tid, gname, rec

    def _admit(self, tenant, gname, operation, **options):
        self.limiter.admit(tenant, operation, **options)
        ensure_schema(self.db, gname)

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
                if kind not in SOURCE_KINDS:
                    raise InvalidArgument("invalid source kind")
                self._admit(tid, gname, "write")
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
                self._admit(tid, gname, "write")
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
                self._admit(tid, gname, "write")
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
            self._admit(tid, gname, "write")
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
            self._admit(tid, gname, "gate", record=record)
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
            self._admit(tid, gname, "revoke", dry_run=dry_run)
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
            self._admit(tid, gname, "reinstate", dry_run=dry_run)
            return _call(lambda: reinstate(self.db, gname, tid, root_id=root_id, dry_run=dry_run, quota=QuotaPolicy(tid, self.registry.get_record(tid).node_cap)))

        @srv.tool()
        def pedigree_blame(tenant_id: str | None = None, token: str | None = None,
                           node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            self._admit(tid, gname, "read")
            return _call(lambda: run_blame(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_impact(tenant_id: str | None = None, token: str | None = None,
                            node_id: str = "", max_depth: int = 12) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            self._admit(tid, gname, "read")
            return _call(lambda: run_impact(self.db, gname, node_id, max_depth=max_depth))

        @srv.tool()
        def pedigree_whatif(tenant_id: str | None = None, token: str | None = None,
                            roots: list[str] | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            self._admit(tid, gname, "whatif")
            return _call(lambda: whatif(self.db, gname, tid, roots or [], reason="what-if"))

        @srv.tool()
        def pedigree_audit_sources(tenant_id: str | None = None, token: str | None = None,
                                   limit: int = 50) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            self._admit(tid, gname, "read")
            return _call(lambda: audit_sources(self.db, gname, limit=limit))

        @srv.tool()
        def pedigree_report(tenant_id: str | None = None, token: str | None = None) -> dict:
            tid, gname, principal = self._resolve(tenant_id, token)
            if gname is None:
                return {"ok": False, "error": {"code": "unauthorized", "message": _UNAUTHORIZED_MSG}}
            self._admit(tid, gname, "read")
            return _call(lambda: report(self.db, gname))

    def run(self, transport: str = "stdio", host: str = "127.0.0.1", port: int = 8011):
        if transport == "stdio":
            self.server.run(transport="stdio")
        elif transport in ("streamable-http", "sse"):
            import uvicorn

            app = (self.server.streamable_http_app(host=host) if transport == "streamable-http"
                   else self.server.sse_app(host=host))
            # Trust the socket peer by default; custom proxy deployments must
            # deliberately configure a trustworthy proxy boundary themselves.
            uvicorn.run(app, host=host, port=port, proxy_headers=False,
                        log_level=self.server.settings.log_level.lower())
        else:
            raise ValueError("unknown transport")


def build_mcp(db=None, settings=None, default_tenant_id=None, default_tenant_token=None, *, limiter=None):
    return PedigreeMCPServer(db, settings, default_tenant_id, default_tenant_token, limiter=limiter)
