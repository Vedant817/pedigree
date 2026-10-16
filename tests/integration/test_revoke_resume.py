"""P-011: crashed/failed revokes must be recoverable (resume, startup recovery, admin resume).

Red-at-parent (P011-RED):
- `revoke()` returned `{"idempotent": True}` when a root already had a `running` Revocation, so a
  revoke killed mid-flight stayed stuck forever.
- `resume_incomplete()` was defined but never invoked (not at startup, not by a CLI/HTTP path).
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pedigree.engine.revoke as revoke_mod
from pedigree.api.app import create_app
from pedigree.api.registry import TenantRegistry
from pedigree.config import Settings, graph_name
from pedigree.db.client import chunks as real_chunks
from pedigree.db.schema import check_invariants
from pedigree.engine.ingest import record_source, remember
from pedigree.engine.revoke import discover, resume_incomplete, revoke

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests" / "integration" / "_crash_driver_revoke.py"
ADMIN = "resume-test-admin-7b31"


def _tenant(db, prefix="res"):
    registry = TenantRegistry(db)
    tid = "res" + uuid.uuid4().hex[:7]
    registry.create_tenant(tid)
    return registry, tid


def _drop(db, registry, tid):
    try:
        db.select(graph_name(tid)).delete()
    except Exception:  # noqa: BLE001 - missing graph raises
        pass
    db.query(registry.gname, "MATCH(t:Tenant {id:$id}) DELETE t", {"id": tid})


def _chain(db, tid, length=7):
    gname = graph_name(tid)
    src = record_source(db, gname, tid, kind="web", uri="https://resume.test/x",
                        integrity="trusted")
    ids = [src.id]
    prev = src.id
    for i in range(length - 1):
        m = remember(db, gname, tid, text=f"link {i}", derived_from=[prev])
        ids.append(m.id)
        prev = m.id
    return ids[0], ids


def _latest_state(db, gname, root_id):
    from pedigree.db import queries as Q
    rows = db.ro_query(gname, Q.Q_REVOCATION_LATEST, {"id": root_id},
                       op="test.latest").result_set or []
    return rows[0][1] if rows else None


def test_crashed_revoke_resumes_to_oracle_state(db, monkeypatch):
    registry, tid = _tenant(db)
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=7)
        monkeypatch.setattr(revoke_mod, "chunks", lambda xs: real_chunks(xs, 2))
        crashed = {"writes": 0}
        orig = db.query

        def q(g, query, params=None, **kw):
            if kw.get("op") == "revoke.write":
                crashed["writes"] += 1
                r = orig(g, query, params, **kw)
                if crashed["writes"] == 1:
                    raise RuntimeError("injected: crash after write chunk")
                return r
            return orig(g, query, params, **kw)

        monkeypatch.setattr(db, "query", q)
        with pytest.raises(RuntimeError, match="injected"):
            revoke(db, gname, tid, root_id=root, reason="crash")

        assert _latest_state(db, gname, root) == "running"

        monkeypatch.undo()
        monkeypatch.setattr(revoke_mod, "chunks", lambda xs: real_chunks(xs, 2))
        res2 = revoke(db, gname, tid, root_id=root, reason="resume")
        assert res2.get("resumed") is True, res2
        assert res2["state"] == "done"
        st = discover(db, gname, [root])
        for i in ids[1:]:
            assert st.get(i) == "tainted", (i, st)
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, registry, tid)


@pytest.mark.parametrize("fail_write", [1, 2])
def test_crash_variants_still_recover(db, monkeypatch, fail_write):
    registry, tid = _tenant(db, "cr" + str(fail_write))
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=7)
        monkeypatch.setattr(revoke_mod, "chunks", lambda xs: real_chunks(xs, 2))
        crashed = {"writes": 0}
        orig = db.query

        def q(g, query, params=None, **kw):
            if kw.get("op") == "revoke.write":
                crashed["writes"] += 1
                r = orig(g, query, params, **kw)
                if crashed["writes"] == fail_write:
                    raise RuntimeError("injected: crash after write")
                return r
            return orig(g, query, params, **kw)

        monkeypatch.setattr(db, "query", q)
        with pytest.raises(RuntimeError):
            revoke(db, gname, tid, root_id=root, reason="crash")
        monkeypatch.undo()
        res2 = revoke(db, gname, tid, root_id=root, reason="resume")
        assert res2.get("resumed") is True, res2
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, registry, tid)


def test_crash_between_barrier_and_fixpoint(db, monkeypatch):
    """Crash after quarantine, before any final write -> still finishes."""
    registry, tid = _tenant(db, "bar")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=4)
        monkeypatch.setattr(revoke_mod, "chunks", lambda xs: real_chunks(xs, 2))
        orig = db.query

        def q(g, query, params=None, **kw):
            if kw.get("op") == "revoke.write":
                raise RuntimeError("injected: crash before write")
            return orig(g, query, params, **kw)

        monkeypatch.setattr(db, "query", q)
        with pytest.raises(RuntimeError):
            revoke(db, gname, tid, root_id=root, reason="crash")
        monkeypatch.undo()
        res2 = revoke(db, gname, tid, root_id=root, reason="resume")
        assert res2.get("resumed") is True, res2
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, registry, tid)


def test_kill_process_then_resume(db):
    registry, tid = _tenant(db, "k")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=7)
        env = {x: y for x, y in __import__("os").environ.items() if x not in ("FALKOR_PORT",)}
        env.update({"PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)})
        proc = subprocess.run(
            [sys.executable, str(DRIVER), tid, root],
            capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=240,
        )
        assert proc.returncode == 7, (proc.stdout, proc.stderr)
        assert _latest_state(db, gname, root) == "running", _latest_state(db, gname, root)
        done = resume_incomplete(db, gname)
        assert done and done[0].get("state") == "done", done
        # roots are excluded from `discover()` (BFS excludes the start node, per the architect
        # note), so probe the root's own status directly:
        rstatus = db.ro_query(gname, "MATCH (n:Node {id:$id}) RETURN n.status", {"id": root}).result_set[0][0]
        assert rstatus == "revoked", rstatus
        st = discover(db, gname, [root])
        for i in ids[1:]:
            assert st.get(i) == "tainted", (i, st)
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, registry, tid)


def test_startup_recovers_running_revocations(db):
    registry, tid = _tenant(db, "s")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=5)
        env = {"PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)}
        env.update({k: v for k, v in __import__("os").environ.items()})
        # crash a second revocation in the DB directly via the driver against this root
        proc = subprocess.run([sys.executable, str(DRIVER), tid, root],
                              capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=240)
        assert proc.returncode == 7, (proc.stdout, proc.stderr)
        assert _latest_state(db, gname, root) == "running"

        settings = Settings(pedigree_admin_token=ADMIN)
        app = create_app(db=db, settings=settings)
        import time as _t
        with TestClient(app) as _client:
            _ = _client
            deadline = _t.time() + 30
            state = _latest_state(db, gname, root)
            while state != "done" and _t.time() < deadline:
                _t.sleep(0.25)
                state = _latest_state(db, gname, root)
            assert state == "done", state
        assert check_invariants(db, gname, tid) == []
    finally:
        _drop(db, registry, tid)


def test_admin_resume_endpoint_and_cli(db):
    registry, tid = _tenant(db, "e")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=5)
        proc = subprocess.run([sys.executable, str(DRIVER), tid, root],
                              capture_output=True, text=True,
                              env={**__import__("os").environ, "PYTHONUTF8": "1"},
                              cwd=str(ROOT), timeout=240)
        assert proc.returncode == 7, (proc.stdout, proc.stderr)
        assert _latest_state(db, gname, root) == "running"

        app = create_app(db=db, settings=Settings(pedigree_admin_token=ADMIN))
        with TestClient(app) as client:
            r = client.post("/v1/admin/resume", headers={"X-Admin-Token": ADMIN},
                            json={"tenant": tid})
            assert r.status_code == 200, r.text
            assert r.json()["tenant"] == tid, r.text
            assert (r.json().get("resumed") or []) and r.json()["resumed"][0]["state"] == "done", r.text
        assert _latest_state(db, gname, root) == "done"
        assert check_invariants(db, gname, tid) == []

    finally:
        _drop(db, registry, tid)


def test_cli_resume_command_runs(db):
    registry, tid = _tenant(db, "c")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=5)
        env = {**__import__("os").environ, "PYTHONUTF8": "1"}
        proc = subprocess.run([sys.executable, str(DRIVER), tid, root],
                              capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=240)
        assert proc.returncode == 7, (proc.stdout, proc.stderr)
        assert _latest_state(db, gname, root) == "running"
        env2 = {k: v for k, v in __import__("os").environ.items() if k != "PEDIGREE_ADMIN_TOKEN"}
        env2.update({"PYTHONUTF8": "1", "PEDIGREE_ADMIN_TOKEN": ADMIN, "PEDIGREE_ENV": "dev"})
        r = subprocess.run([sys.executable, "-m", "pedigree.cli", "resume", "--tenant", tid],
                           capture_output=True, text=True, env=env2, cwd=str(ROOT), timeout=240)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert _latest_state(db, gname, root) == "done", r.stdout + r.stderr
    finally:
        _drop(db, registry, tid)


def test_revoke_done_row_stays_idempotent(db):
    registry, tid = _tenant(db, "idm")
    try:
        gname = graph_name(tid)
        root, ids = _chain(db, tid, length=4)
        r1 = revoke(db, gname, tid, root_id=root, reason="once")
        assert "resumed" not in r1 and r1["state"] == "done"
        r2 = revoke(db, gname, tid, root_id=root, reason="again")
        assert r2.get("idempotent") is True
        assert r2.get("state") == "done"
    finally:
        _drop(db, registry, tid)
