"""Manual independent release probe. Only run against a named owned review DB.

Not collected by pytest: restarts an explicitly named disposable Docker container.
No existing application, volume, or deployment is used.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import Db


def main():
    container = os.environ["INDEPENDENT_QA_CONTAINER"]
    ports = {"pedigree-independent-qa-20261018-6385": "6385",
             "pedigree-round2-6389": "6389"}
    assert container in ports
    db_port = ports[container]
    info = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    assert info["Config"]["Image"] == "falkordb/falkordb:v4.22.1"
    assert info["Mounts"] == []
    assert info["NetworkSettings"]["Ports"]["6379/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": db_port}]
    assert os.environ["FALKOR_PORT"] == db_port
    db = Db(Settings(_env_file=None))
    assert db.module_version() == 42201
    registry = TenantRegistry(db)
    assert registry.list_tenants() == [], "probe requires the owned empty test registry"
    print("EMPTY: module 42201; zero tenants; no mounted volumes", flush=True)
    db.client.connection.config_set("appendonly", "yes")
    db.client.connection.config_set("appendfsync", "always")
    admin = secrets.token_urlsafe(32)
    env = {**os.environ, "PEDIGREE_ENV": "production", "PEDIGREE_ADMIN_TOKEN": admin,
           "PEDIGREE_DB_ACL_SECRET": secrets.token_urlsafe(32), "PEDIGREE_DB_ACL": "true",
           "PEDIGREE_SEED_DEMO": "0", "PEDIGREE_DEMO_LOGIN": "0"}
    tenant = "runtime" + uuid.uuid4().hex[:10]
    child = None
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 8119 if db_port == "6389" else 0))
        port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="pedigree-independent-") as temporary:
        log = (Path(temporary) / "service.log").open("w", encoding="utf-8")
        def start():
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "pedigree.api.app:create_app",
                "--factory", "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers"],
                env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                assert process.poll() is None, "owned production server exited"
                try:
                    if httpx.get(origin + "/readyz", timeout=.5).status_code == 200:
                        return process
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            process.terminate()
            process.wait(5)
            raise AssertionError("owned production server readiness deadline exceeded")
        try:
            child = start()
            with httpx.Client(base_url=origin, timeout=10) as client:
                assert client.get("/v1/ui/config").json() == {"demo_login": False, "api_docs": False}
                assert client.get("/docs").status_code == 404
                assert client.get("/admin/tenants", headers={"x-admin-token": admin}).json() == {"tenants": []}
                print("PRODUCTION: ready=200; tenants=[]; demo=false; docs=false/404", flush=True)
                result = client.post("/admin/tenants", headers={"x-admin-token": admin}, json={"id": tenant})
                assert result.status_code == 200
                auth = {"Authorization": "Bearer " + result.json()["agent_token"]}
                body = {"runtime": "claude-code", "session_id": "runtime_session", "delivery_id": "runtime_delivery",
                        "events": [{"type": "session"}, {"type": "source_read", "source_kind": "file",
                                    "uri": "synthetic.py", "content_hash": "a" * 64}]}
                first = client.post("/v1/events", headers=auth, json=body)
                assert first.status_code == 200
                child.terminate()
                child.wait(5)
                child = start()
                assert client.post("/v1/events", headers=auth, json=body).json() == first.json()
                print("API RESTART: same persisted receipt acknowledged", flush=True)
                subprocess.run(["docker", "restart", container], check=True, stdout=subprocess.DEVNULL, timeout=30)
                deadline = time.monotonic() + 15
                while not db.ping() and time.monotonic() < deadline:
                    time.sleep(.1)
                assert db.ping() and db.module_version() == 42201
                assert client.post("/v1/events", headers=auth, json=body).json() == first.json()
                assert db.ro_query(graph_name(tenant), "MATCH(n:Source) RETURN count(n)").result_set == [[1]]
                print("DB RESTART: persisted source/receipt; ACL reprovisioned; exact replay; one source", flush=True)
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(5)
            log.close()
            if graph_name(tenant) in db.list_graphs():
                db.select(graph_name(tenant)).delete()
            db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tenant})
            db.execute_admin("ACL", "DELUSER", "t_" + tenant)
    print("CLEANUP: owned API stopped; exact synthetic graph/tenant removed", flush=True)


if __name__ == "__main__":
    main()
