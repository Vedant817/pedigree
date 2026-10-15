"""Per-tenant DB users with key-pattern ACLs (VERIFIED on 4.22.1). Graph names 'ped:<tenant>' (+ 'ped:<tenant>:wi:<id>' what-if copies);
tenant ids are [a-z0-9]{3,24} so pattern ~ped:abc can never match tenant 'abcd'. Run: FALKOR_PORT=6390 python 13_acl_tenant_isolation.py"""
import os
from falkordb import FalkorDB
admin = FalkorDB(host=os.getenv("FALKOR_HOST","localhost"), port=int(os.getenv("FALKOR_PORT","6379")))
for t in ("abc", "abcd"):
    admin.select_graph(f"ped:{t}").query("MERGE (:Node {id:'x'})")
    # (a) +info is REQUIRED because the python client runs INFO on connect; (b) %R~ patterns did not allow GRAPH.RO_QUERY here -> use ~pattern
    admin.connection.execute_command("ACL","SETUSER",f"t_{t}","on",">pw","resetkeys",f"~ped:{t}",f"~ped:{t}:wi:*","-@all","+info","+ping",
        "+graph.query","+graph.ro_query","+graph.explain","+graph.delete","+graph.copy","+graph.constraint","+graph.list")
db = FalkorDB(host=os.getenv("FALKOR_HOST","localhost"), port=int(os.getenv("FALKOR_PORT","6379")), username="t_abc", password="pw")
ok = db.select_graph("ped:abc").query("MERGE (:Node {id:'y'}) RETURN 1").result_set; assert ok == [[1]]
for other in ("ped:abcd", "ped:zzz"):
    try: db.select_graph(other).ro_query("MATCH (n) RETURN count(n)"); raise SystemExit(f"LEAK: read {other}")
    except Exception as e: assert "No permissions" in str(e), e; print("denied:", other)
db.select_graph("ped:abc").copy("ped:abc:wi:1"); db.select_graph("ped:abc:wi:1").delete(); print("what-if copy within own namespace: ok")
try: db.select_graph("ped:abc").copy("ped:abcd:evil"); raise SystemExit("LEAK: copy into other namespace")
except Exception as e: print("copy into foreign namespace denied:", str(e)[:60])
print("NOTE: GRAPH.LIST returns ALL graph names to any user with +graph.list (metadata leak) -> never expose DB creds to clients; remove +graph.list if unused.")
for t in ("abc","abcd"): admin.select_graph(f"ped:{t}").delete()
print("OK")
