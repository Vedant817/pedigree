// uses the sdk from ../ts/node_modules
import { Client } from '../ts/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import { StdioClientTransport } from '../ts/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
const t = new StdioClientTransport({ command: 'node', args: ['node_modules/@falkordb/mcpserver/dist/index.js'], env: { ...process.env, FALKORDB_HOST: 'localhost', FALKORDB_PORT: '6379' } });
const c = new Client({ name: 's', version: '0' }); await c.connect(t);
const tools = (await c.listTools()).tools; console.log(tools.map(x => x.name));
const call = async (name, args) => { const r = await c.callTool({ name, arguments: args }); console.log(name, '->', JSON.stringify(r.content).slice(0, 300)); };
await call('list_graphs', {});
await call('query_graph', { graphName: 'tenant_smoke', query: 'MATCH (n) RETURN count(n) AS n' });
await call('query_graph_readonly', { graphName: 'tenant_smoke', query: 'MATCH (m:Memory {id:$id}) RETURN m.status', params: { id: 'm1' } });
await call('get_graph_schema', { graphName: 'tenant_smoke' });
await c.close(); process.exit(0);
