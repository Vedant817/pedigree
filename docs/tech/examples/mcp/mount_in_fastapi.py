"""SPIKE (verified on mcp 2.3.0): mount an MCPServer's streamable-HTTP ASGI app inside FastAPI,
next to normal REST routes, with a bearer-token check as ASGI middleware.
run:  python mount_in_fastapi.py   (port 8766)   then:  python client_smoke.py http://127.0.0.1:8766/mcp
(Client must send header Authorization: Bearer $MCP_TOKEN when MCP_TOKEN is set; client_smoke does not, so leave it unset for the smoke.)"""
import contextlib, os
from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("pedigree-spike")

@mcp.tool()
def ping(x: str) -> str:
    """echo"""
    return x

mcp_app = mcp.streamable_http_app()          # Starlette app; its own route is /mcp

@contextlib.asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():     # REQUIRED when mounted: starts the task group
        yield

app = FastAPI(lifespan=lifespan)

@app.get("/healthz")
def healthz():
    return {"ok": True}

TOKEN = os.environ.get("MCP_TOKEN")
class Bearer:
    def __init__(self, inner): self.inner = inner
    async def __call__(self, scope, receive, send):
        if TOKEN and scope["type"] == "http":
            h = dict(scope["headers"]).get(b"authorization", b"").decode()
            if h != f"Bearer {TOKEN}":
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'}); return
        await self.inner(scope, receive, send)

app.mount("/", Bearer(mcp_app))               # mount LAST so /healthz and REST routes win; MCP at /mcp

if __name__ == "__main__":
    import uvicorn; uvicorn.run(app, host="127.0.0.1", port=8766)
