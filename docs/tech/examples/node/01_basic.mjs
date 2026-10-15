// node 01_basic.mjs   (npm i falkordb ; client v6.8.0 verified)
import { FalkorDB } from 'falkordb';
const db = await FalkorDB.connect({ socket: { host: process.env.FALKOR_HOST || 'localhost', port: +(process.env.FALKOR_PORT || 6379) } });
// per-tenant graph
const g = db.selectGraph('node_demo');
try { await g.delete(); } catch {}
await g.query(`CREATE INDEX FOR (m:Memory) ON (m.id)`);
await g.query(
  `CREATE (s:Source {id:$sid, trust:0.4}), (a:Memory {id:'a', status:'valid'}), (b:Memory {id:'b', status:'valid'}),
          (a)-[:DERIVED_FROM]->(s), (b)-[:DERIVED_FROM]->(a), (s)-[:FEEDS]->(a), (a)-[:FEEDS]->(b)`,
  { params: { sid: 's1' } });
// variable-length transitive closure (parameterised source id)
const r = await g.roQuery(
  `MATCH (s:Source {id:$sid})<-[:DERIVED_FROM*1..10]-(m:Memory) RETURN DISTINCT m.id AS id ORDER BY id`,
  { params: { sid: 's1' } });
console.log('descendants of s1:', r.data);                     // [ { id: 'a' }, { id: 'b' } ]
// BFS (linear-time, visited-set) over the mirrored FEEDS edges
const bfs = await g.roQuery(`MATCH (s:Source {id:'s1'}) CALL algo.BFS(s,-1,'FEEDS') YIELD nodes RETURN [n IN nodes | n.id] AS ids`);
console.log('BFS:', bfs.data);
// atomic cascade write
const w = await g.query(
  `MATCH (s:Source {id:$sid}) SET s.status='retracted' WITH s CALL algo.BFS(s,10,'FEEDS') YIELD nodes
   UNWIND nodes AS m SET m.status='invalidated' RETURN count(m) AS n`, { params: { sid: 's1' } });
console.log('invalidated:', w.data, 'metadata:', w.metadata);
// timeout (ms) is an option: { params, TIMEOUT }
try { await g.roQuery(`UNWIND range(1,100000000) AS x RETURN sum(x)`, { TIMEOUT: 50 }); } catch (e) { console.log('timeout error:', e.message); }
console.log('graphs:', (await db.list()).length);
// vector example: store embedding with vecf32(), query with db.idx.vector.queryNodes
await g.query(`CREATE VECTOR INDEX FOR (m:Memory) ON (m.emb) OPTIONS {dimension:4, similarityFunction:'cosine'}`);
await g.query(`MATCH (m:Memory {id:'a'}) SET m.emb = vecf32($v)`, { params: { v: [1, 0, 0, 0] } });
await new Promise(r => setTimeout(r, 500));
const v = await g.roQuery(`CALL db.idx.vector.queryNodes('Memory','emb',1,vecf32($v)) YIELD node,score RETURN node.id AS id, score`, { params: { v: [1, 0, 0, 0] } });
console.log('vector:', v.data);
await g.delete();
await db.close();
