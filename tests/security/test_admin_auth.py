"""P-013: admin auth must be fail-closed (FIX_PROMPT A3; red-team required at close).

Red-at-parent:
- `admin.py` gated the token check behind `registry.has_tenants()`: with an EMPTY registry
  `POST/GET /admin/tenants` skipped auth entirely, so a fresh deploy was owned by the first
  caller.
- The compare was plain `!=` (not constant-time); nothing refused an empty/known-default
  admin token at startup or in a CLI, and no first-run CLI path existed at all.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.errors import NotFoundInGraph

ADMIN = "test-admin-strong-9f2c4e"
KNOWN_DEFAULT = "change-me-admin"
ROOT = Path(__file__).resolve().parents[2]


def _client(db, token=ADMIN, env="production"):
    settings = Settings(pedigree_admin_token=token, pedigree_env=env)
    return TestClient(create_app(db=db, settings=settings))


def _tid(prefix="adm"):
    return prefix + uuid.uuid4().hex[:8]


def _cleanup(db, *tenants):
    reg = TenantRegistry(db)
    for t in tenants:
        try:
            db.select(graph_name(t)).delete()
        except Exception:  # noqa: BLE001 - missing graph raises
            pass
        db.query(reg.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": t})


def test_fresh_registry_bootstrap_is_fail_closed(db, monkeypatch):
    """With an EMPTY registry the old code skipped auth; it must now still 401."""
    monkeypatch.setattr(TenantRegistry, "has_tenants", lambda self: False)
    client = _client(db)
    tid = _tid("boot")
    try:
        r = client.post("/admin/tenants", json={"id": tid})
        assert r.status_code == 401, r.text
        r = client.get("/admin/tenants")
        assert r.status_code == 401, r.text
        with pytest.raises(NotFoundInGraph):
            TenantRegistry(db).get_record(tid)
    finally:
        _cleanup(db, tid)


def test_admin_token_matrix(db):
    client = _client(db)
    tid = _tid()
    try:
        assert client.post("/admin/tenants", json={"id": tid}).status_code == 401
        assert client.post("/admin/tenants", headers={"X-Admin-Token": ""},
                           json={"id": tid}).status_code == 401
        assert client.post("/admin/tenants", headers={"X-Admin-Token": "wrong"},
                           json={"id": tid}).status_code == 401
        assert client.get("/admin/tenants", headers={"X-Admin-Token": "wrong"}).status_code == 401
        assert client.get("/admin/tenants", headers={"X-Admin-Token": ADMIN}).status_code == 200
        r = client.post("/admin/tenants", headers={"X-Admin-Token": ADMIN}, json={"id": tid})
        assert r.status_code == 200, r.text
        assert r.json()["token"].startswith("ped_")
    finally:
        _cleanup(db, tid)


def test_startup_guard_matrix(db):
    with pytest.raises(RuntimeError):
        create_app(db=db, settings=Settings(pedigree_env="production", pedigree_admin_token=""))
    with pytest.raises(RuntimeError):
        create_app(db=db, settings=Settings(pedigree_env="production",
                                            pedigree_admin_token=KNOWN_DEFAULT))
    assert create_app(db=db, settings=Settings(pedigree_env="production",
                                               pedigree_admin_token=ADMIN)) is not None
    assert create_app(db=db, settings=Settings(pedigree_env="dev",
                                               pedigree_admin_token=KNOWN_DEFAULT)) is not None


def _cli(args, token, env_name="production", drop_token=False):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PEDIGREE_ADMIN_TOKEN", "PEDIGREE_ENV")}
    env["PEDIGREE_ENV"] = env_name
    if not drop_token and token is not None:
        env["PEDIGREE_ADMIN_TOKEN"] = token
    return subprocess.run([sys.executable, "-m", "pedigree.cli", "admin", *args],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=90)


def test_cli_admin_create_tenant_first_run(db):
    tid = _tid("cli")
    try:
        r = _cli(["create-tenant", "--id", tid], token=ADMIN)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert tid in r.stdout and "ped_" in r.stdout
        assert TenantRegistry(db).get_record(tid).status == "active"
    finally:
        _cleanup(db, tid)


def test_cli_refuses_default_token_in_prod(db):
    tid = _tid("clip")
    try:
        r = _cli(["create-tenant", "--id", tid], token=KNOWN_DEFAULT)
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "PEDIGREE_ADMIN_TOKEN" in (r.stderr or "")
        with pytest.raises(NotFoundInGraph):
            TenantRegistry(db).get_record(tid)
    finally:
        _cleanup(db, tid)


def test_cli_refuses_missing_token_in_prod(db):
    tid = _tid("clim")
    try:
        r = _cli(["create-tenant", "--id", tid], token=None, drop_token=True)
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "PEDIGREE_ADMIN_TOKEN" in (r.stderr or "")
        with pytest.raises(NotFoundInGraph):
            TenantRegistry(db).get_record(tid)
    finally:
        _cleanup(db, tid)
