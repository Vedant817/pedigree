#!/usr/bin/env bash
# Kill -9 the server mid-life and restart: does data survive?  (AOF appendfsync default = everysec => up to ~1s of writes can be lost on crash)
set -e; cd "$(dirname "$0")"; . .venv/bin/activate; SP=$(ls -d $PWD/.venv/lib/python3*/site-packages/redislite/bin); R="$SP/redis-cli"
python - <<'P'
import sys; sys.path.insert(0,'examples/py')
from common import connect, fresh_graph
db=connect(); g=fresh_graph(db,'restart_test'); g.query("CREATE INDEX FOR (m:M) ON (m.id)"); g.query("UNWIND range(1,5000) AS i CREATE (:M {id:i})")
print("written 5000 nodes; waiting 2s for AOF everysec fsync"); 
P
sleep 2; pkill -9 -f "redis-server.*6379" ; sleep 1
(nohup ./start-falkordb.sh >> data/server.log 2>&1 &); for i in $(seq 1 60); do $R PING >/dev/null 2>&1 && break; sleep 0.5; done
python - <<'P'
import sys, time; sys.path.insert(0,'examples/py')
from common import connect
db=connect(); g=db.select_graph('restart_test'); t=time.time()
print("after kill -9 + restart: nodes =", g.ro_query("MATCH (n:M) RETURN count(n)").result_set[0][0], "| indexes:", [r[0] for r in g.ro_query("CALL db.indexes()").result_set])
print("graphs present:", len(db.list_graphs()))
P
