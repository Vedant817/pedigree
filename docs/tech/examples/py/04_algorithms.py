"""Path + graph algorithms available in FalkorDB 4.18.3. Procedure list: see bench/procedures.txt (CALL dbms.procedures())."""
from common import connect, fresh_graph
db = connect(); g = fresh_graph(db, "demo_algo")
# two clusters {0..4} {5..9} joined by a bridge 4->5 ; chain-ish DAG with a diamond
g.query("""UNWIND range(0,9) AS i CREATE (:M {id:i})""")
edges = [(0,1),(1,2),(0,2),(2,3),(3,4),(4,0),(5,6),(6,7),(5,7),(7,8),(8,9),(9,5),(4,5)]
g.query("UNWIND $e AS e MATCH (a:M {id:e[0]}),(b:M {id:e[1]}) CREATE (a)-[:DERIVED_FROM {w:1.0}]->(b)", {"e": [list(x) for x in edges]})

def show(title, q, p=None):
    r = g.ro_query(q, p); print(f"-- {title}\n   {r.result_set}")
    return r

# transitive closure with variable-length path (DISTINCT needed). Max depth must be bounded *N for safety; *1.. is allowed.
show("descendants of 0 within 10 hops", "MATCH (a:M {id:0})-[:DERIVED_FROM*1..10]->(x) RETURN DISTINCT x.id ORDER BY x.id")
show("ancestors (reverse arrow)",       "MATCH (a:M {id:9})<-[:DERIVED_FROM*1..10]-(x) RETURN DISTINCT x.id ORDER BY x.id")
show("var-len with edge property filter (inline map only)", "MATCH (a:M {id:0})-[:DERIVED_FROM*1..3 {w:1.0}]->(x) RETURN DISTINCT x.id ORDER BY x.id")
show("var-len with path predicate", "MATCH p=(a:M {id:0})-[:DERIVED_FROM*1..5]->(x) WHERE all(n IN nodes(p) WHERE n.id <> 3) RETURN DISTINCT x.id ORDER BY x.id")
show("path length + node list", "MATCH p=(a:M {id:0})-[:DERIVED_FROM*1..5]->(x:M {id:4}) RETURN length(p), [n IN nodes(p)|n.id] ORDER BY length(p)")

# shortestPath: ONLY allowed in WITH/RETURN, both endpoints already bound by a previous MATCH
show("shortestPath", "MATCH (a:M {id:0}),(b:M {id:9}) RETURN shortestPath((a)-[:DERIVED_FROM*]->(b)) AS p")
show("shortestPath as list", "MATCH (a:M {id:0}),(b:M {id:9}) WITH shortestPath((a)-[:DERIVED_FROM*]->(b)) AS p RETURN length(p), [n IN nodes(p)|n.id]")
# allShortestPaths: ONLY allowed in MATCH, and endpoints must be bound by an EARLIER clause separated by WITH (verified: without the WITH it errors
# "Source and destination must already be resolved")
show("allShortestPaths", "MATCH (a:M {id:0}),(b:M {id:3}) WITH a,b MATCH p=allShortestPaths((a)-[:DERIVED_FROM*]->(b)) RETURN length(p), [n IN nodes(p)|n.id]")

show("algo.BFS (unbounded, edge-type filter) from node 0",
     "MATCH (a:M {id:0}) CALL algo.BFS(a, -1, 'DERIVED_FROM') YIELD nodes, edges RETURN size(nodes), size(edges)")
show("algo.BFS depth<=2", "MATCH (a:M {id:0}) CALL algo.BFS(a, 2, 'DERIVED_FROM') YIELD nodes RETURN [n IN nodes | n.id]")

show("algo.pageRank(label, relType) top3", "CALL algo.pageRank('M','DERIVED_FROM') YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT 3")
show("algo.betweenness top3 (config map form)", "CALL algo.betweenness({nodeLabels:['M'], relationshipTypes:['DERIVED_FROM']}) YIELD node, score RETURN node.id, score ORDER BY score DESC LIMIT 3")
show("algo.WCC components", "CALL algo.WCC({nodeLabels:['M'], relationshipTypes:['DERIVED_FROM']}) YIELD node, componentId RETURN componentId, count(*)")
# NOTE: there is NO algo.CDLP / louvain / leiden / triangleCount in 4.18.3. Community detection = label propagation:
show("algo.labelPropagation (CDLP equivalent)", "CALL algo.labelPropagation({nodeLabels:['M'], relationshipTypes:['DERIVED_FROM'], maxIterations:10}) YIELD node, communityId RETURN communityId, collect(node.id)")
show("algo.SPpaths (weighted k shortest)", "MATCH (a:M {id:0}),(b:M {id:9}) CALL algo.SPpaths({sourceNode:a, targetNode:b, relTypes:['DERIVED_FROM'], pathCount:3}) YIELD path, pathCost RETURN pathCost, length(path)")
show("algo.SSpaths (single source)", "MATCH (a:M {id:0}) CALL algo.SSpaths({sourceNode:a, relTypes:['DERIVED_FROM'], maxLen:3, pathCount:5}) YIELD path, pathCost RETURN length(path), pathCost")
show("algo.MSF yields", "CALL dbms.procedures() YIELD name WHERE name='algo.MSF' RETURN name")
