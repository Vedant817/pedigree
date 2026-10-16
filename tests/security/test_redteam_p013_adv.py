"""Red-team P-013 additional adversarial tests (must currently FAIL)."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name

ADMIN = "test-admin-strong-9f2c4e"
ROOT = Path(__file__).resolve().parents[2]


def _client(db, token=ADMIN, env="production"):
    settings = Settings(pedigree_admin_token=token, pedigree_env=env)
    return TestClient(create_app(db=db, settings=settings)), settings


def _cleanup(db, *tenants):
    reg = TenantRegistry(db)
    for t in tenants:
        try:
            db.select(graph_name(t)).delete()
        except Exception:  # noqa: BLE001
            pass
        try:
            db.query(reg.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": t})
        except Exception:  # noqa: BLE001
            pass


def _cli(args, token, env_name="production", drop_token=False):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PEDIGREE_ADMIN_TOKEN", "PEDIGREE_ENV")}
    env["PEDIGREE_ENV"] = env_name
    if not drop_token and token is not None:
        env["PEDIGREE_ADMIN_TOKEN"] = token
    return subprocess.run([sys.executable, "-m", "pedigree.cli", "admin", *args],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=90)


def test_admin_create_rejects_invalid_tenant_id(db):
    client, _ = _client(db)
    try:
        r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                         json={"id": "../../etc"})
        assert r.status_code in (400, 404, 422), r.text
    finally:
        _cleanup(db, "dummy")


def test_admin_create_rejects_graph_name_trick_id(db):
    client, _ = _client(db)
    try:
        r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                         json={"id": "ped:abcd"})
        assert r.status_code in (400, 404, 422), r.text
    finally:
        pass


def test_admin_create_bounds_node_cap(db):
    client, _ = _client(db)
    tid = "rt13cap" + uuid.uuid4().hex[:6]
    try:
        r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                         json={"id": tid, "node_cap": -1})
        assert r.status_code in (400, 422), r.text
        r2 = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN},
                          json={"id": tid + "b", "node_cap": 10**12})
        assert r2.status_code in (400, 422), r2.text
    finally:
        _cleanup(db, tid, tid + "b")


def test_admin_header_whitespace_normalized(db):
    padded = "  " + ADMIN + "  "
    settings = Settings(pedigree_admin_token=padded, pedigree_env="production")
    client = TestClient(create_app(db=db, settings=settings))
    r = client.get("/admin/tenants", headers={"X-Admin-Token": ADMIN})
    assert r.status_code == 200, r.text


def test_cli_rejects_invalid_tenant_id(db):
    r = _cli(["create-tenant", "--id", "../../etc"], token=ADMIN)
    assert r.returncode != 0, (r.stdout, r.stderr)


def test_cli_rejects_zero_cap(db):
    tid = "rt13zcap" + uuid.uuid4().hex[:6]
    try:
        r = _cli(["create-tenant", "--id", tid, "--cap", "0"], token=ADMIN)
        assert r.returncode != 0, (r.stdout, r.stderr)
    finally:
        _cleanup(db, tid)
