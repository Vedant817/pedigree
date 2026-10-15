// node server_ts.mjs          -> stdio
// node server_ts.mjs http 8766 -> streamable HTTP (stateless) at http://127.0.0.1:8766/mcp
// @modelcontextprotocol/sdk 1.32.1 (v1 API: McpServer + registerTool). npm view shows a v2 split-package line (@modelcontextprotocol/server 2.3.x) - NOT tested here.
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';
import { FalkorDB } from 'falkordb';
import express from 'express';

const db = await FalkorDB.connect({ socket: { host: process.env.FALKOR_HOST || 'localhost', port: +(process.env.FALKOR_PORT || 6379) } });
const G = (tenant) => db.selectGraph(`tenant_${tenant}`);

function build() {
  const s = new McpServer({ name: 'provenance-ts', version: '0.1.0' });
  s.registerTool('retract_source', {
    description: 'Retract a source; cascade-invalidate derived memories (depth<=10, BFS over FEEDS)',
    inputSchema: { tenant: z.string(), source_id: z.string(), reason: z.string() },
  }, async ({ tenant, source_id, reason }) => {
    const r = await G(tenant).query(
      `MATCH (s:Source {id:$sid}) SET s.status='retracted', s.reason=$why
       WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes UNWIND nodes AS m SET m.status='invalidated' RETURN collect(m.id) AS ids`,
      { params: { sid: source_id, why: reason } });
    return { content: [{ type: 'text', text: JSON.stringify({ invalidated: r.data?.[0]?.ids ?? [] }) }] };
  });
  s.registerTool('ping', { description: 'health', inputSchema: {} }, async () => ({ content: [{ type: 'text', text: 'pong' }] }));
  return s;
}

if (process.argv[2] === 'http') {
  const app = express(); app.use(express.json());
  app.post('/mcp', async (req, res) => {            // stateless: new server+transport per request
    const t = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => t.close());
    const srv = build(); await srv.connect(t); await t.handleRequest(req, res, req.body);
  });
  app.listen(+(process.argv[3] || 8766), '127.0.0.1', () => console.error('listening'));
} else {
  await build().connect(new StdioServerTransport());
}
