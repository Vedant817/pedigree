"""Minimal provenance MCP server (Python, official SDK mcp==2.3.0, class MCPServer; in mcp<2 it is `from mcp.server.fastmcp import FastMCP`).
   python server_py.py            -> stdio (for opencode "local" servers)
   python server_py.py http 8765  -> streamable HTTP at http://127.0.0.1:8765/mcp  (for opencode "remote" servers)
Tools are tenant-scoped: graph name = f"tenant_{tenant}" -> hard isolation, one graph per tenant.
NEVER print() to stdout in stdio mode (it is the protocol channel); log to stderr.
"""
import os, sys, json
from falkordb import FalkorDB
try:
    from mcp.server.mcpserver import MCPServer as _Server      # mcp >= 2
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server           # mcp 1.x
mcp = _Server("provenance-memory")
_db = FalkorDB(host=os.getenv("FALKOR_HOST", "localhost"), port=int(os.getenv("FALKOR_PORT", "6379")), password=os.getenv("FALKOR_PASSWORD") or None)
_ready = set()
def G(tenant: str):
    name = f"tenant_{tenant}"
    g = _db.select_graph(name)
    if name not in _ready:
        for lab in ("Source", "Memory", "Decision"):
            try: g.query(f"CREATE INDEX FOR (n:{lab}) ON (n.id)")
            except Exception: pass                              # "already indexed" raises ResponseError
        _ready.add(name)
    return g

@mcp.tool()
def add_memory(tenant: str, id: str, text: str, derived_from: list[str], kind: str = "memory", trust: float = 0.5) -> str:
    """Store a memory node linked to the sources/memories it was derived from (ids). Creates a Source node when kind='source'."""
    g = G(tenant)
    if kind == "source":
        g.query("MERGE (s:Source {id:$id}) SET s.text=$t, s.trust=$tr, s.status='active'", {"id": id, "t": text, "tr": trust})
        return f"source {id} stored"
    g.query("MERGE (m:Memory {id:$id}) SET m.text=$t, m.status='valid', m.created_at=timestamp()", {"id": id, "t": text})
    g.query("""MATCH (m:Memory {id:$id}) UNWIND $parents AS pid MATCH (p) WHERE (p:Source OR p:Memory) AND p.id = pid
               MERGE (m)-[:DERIVED_FROM]->(p) MERGE (p)-[:FEEDS]->(m)""", {"id": id, "parents": derived_from})
    return f"memory {id} stored with {len(derived_from)} parent link(s)"

@mcp.tool()
def retract_source(tenant: str, source_id: str, reason: str) -> dict:
    """Retract a source and cascade-invalidate every memory derived from it (depth<=10). Returns invalidated ids and decisions to revisit."""
    g = G(tenant)
    r = g.query("""MATCH (s:Source {id:$sid}) SET s.status='retracted', s.reason=$why
                   WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m
                   SET m.status='invalidated', m.invalidated_by=s.id RETURN collect(m.id)""", {"sid": source_id, "why": reason})
    ids = r.result_set[0][0] if r.result_set else []
    d = g.ro_query("MATCH (d:Decision)-[:DEPENDS_ON]->(m:Memory) WHERE m.id IN $ids RETURN DISTINCT d.id, d.title", {"ids": ids}).result_set
    return {"invalidated": ids, "decisions_to_revisit": [{"id": x[0], "title": x[1]} for x in d]}

@mcp.tool()
def explain_memory(tenant: str, id: str) -> dict:
    """Why do I believe this? Returns the memory, its status and every ancestor (sources first)."""
    g = G(tenant)
    r = g.ro_query("MATCH (m:Memory {id:$id}) CALL algo.BFS(m,10,'DERIVED_FROM') YIELD nodes RETURN m.status, [n IN nodes | [n.id, labels(n)[0], n.status]]", {"id": id}).result_set
    return {"status": r[0][0], "ancestors": r[0][1]} if r else {"error": "not found"}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "http":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
        try: mcp.run("streamable-http", host="127.0.0.1", port=port)       # mcp>=2: transport args go to run()
        except TypeError: mcp.settings.host, mcp.settings.port = "127.0.0.1", port; mcp.run("streamable-http")   # mcp 1.x
    else:
        mcp.run("stdio")
