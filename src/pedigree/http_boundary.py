"""Bound request bytes before parsers, dispatch and writes, including chunked bodies."""
from __future__ import annotations

from starlette.responses import JSONResponse

from .config import LIMITS
from .diagnostics import correlation_id


class BodySizeMiddleware:
    def __init__(self, app, max_bytes=None):
        self.app = app
        self.max_bytes = LIMITS["body_bytes"] if max_bytes is None else max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def reject(status, code):
            state = scope.setdefault("state", {})
            cid = state.setdefault("correlation_id", correlation_id())
            response = JSONResponse(status_code=status, content={"error": {"code": code,
                                    "correlation_id": cid}}, headers={"x-correlation-id": cid})
            await response(scope, receive, send)

        lengths = [value for name, value in scope.get("headers", ()) if name.lower() == b"content-length"]
        if len(lengths) > 1:
            await reject(400, "invalid_argument")
            return
        if lengths:
            try:
                raw = lengths[0]
                if not raw or not raw.isdigit():
                    raise ValueError
                declared = int(raw)
            except (ValueError, TypeError):
                await reject(400, "invalid_argument")
                return
            if declared > self.max_bytes:
                await reject(413, "too_large")
                return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                await reject(400, "invalid_argument")
                return
            chunk = message.get("body", b"")
            if len(chunk) > self.max_bytes - len(body):
                await reject(413, "too_large")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
