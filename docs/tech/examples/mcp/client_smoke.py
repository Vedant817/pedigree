"""Smoke test with the official SDK client (mcp 2.x API: mcp.Client). usage: python client_smoke.py stdio | http://127.0.0.1:8765/mcp"""
import asyncio, sys, json, os
from mcp import Client, StdioServerParameters
async def main(target):
    here = os.path.dirname(os.path.abspath(__file__))
    srv = StdioServerParameters(command=sys.executable, args=[os.path.join(here, "server_py.py")]) if target == "stdio" else target
    async with Client(srv) as c:
        tools = await c.list_tools()
        print("tools:", [t.name for t in tools.tools])
        T = "smoke"
        print(await c.call_tool("add_memory", {"tenant": T, "id": "s1", "text": "a blog said X", "derived_from": [], "kind": "source", "trust": 0.2}))
        await c.call_tool("add_memory", {"tenant": T, "id": "m1", "text": "X implies Y", "derived_from": ["s1"]})
        await c.call_tool("add_memory", {"tenant": T, "id": "m2", "text": "so do Z", "derived_from": ["m1"]})
        r = await c.call_tool("explain_memory", {"tenant": T, "id": "m2"}); print("explain:", r.structured_content or r.content)
        r = await c.call_tool("retract_source", {"tenant": T, "source_id": "s1", "reason": "debunked"}); print("retract:", r.structured_content or r.content)
asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "stdio"))
