"""Real FalkorDB recovery, including a killed Python process after RENAME."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pedigree.config import checkpoint_graph_name
from pedigree.engine.checkpoint import Checkpoints
from pedigree.engine.ingest import record_source, remember
from pedigree.errors import Conflict, InvalidArgument, NotFoundInGraph, Unavailable


@pytest.fixture
def snapshots(fresh_graph):
    db, tenant, graph = fresh_graph
    record_source(db, graph, tenant, id="original", kind="file", uri="local:original")
    manager = Checkpoints(db, tenant)
    try:
        yield manager
    finally:
        # This fixture owns exactly one random tenant namespace.
        for name in db.list_graphs():
            if name.startswith(graph + ":ck:"):
                db.select(name).delete()
        db.client.connection.delete(manager.key, manager.index)


def add_later(manager):
    record_source(manager.db, manager.main, manager.tenant,
                  id="later", kind="file", uri="local:later")


def test_immutable_roundtrip_and_retained_rollback(snapshots):
    m = snapshots
    remember(m.db, m.main, m.tenant, id="memory", derived_from=["original"], text="Own recovery fixture")
    original = m._fingerprint(m.main)
    m.create("before")
    with pytest.raises(Conflict):
        m.create("before")
    add_later(m)
    changed = m._fingerprint(m.main)
    result = m.restore("before")
    assert m._fingerprint(m.main) == original
    with pytest.raises(Conflict):
        m.db.query(m.main, "CREATE (:Node {id:$id})", {"id": "original"})
    assert m._fingerprint(checkpoint_graph_name(m.tenant, result["rollback"])) == changed
    assert m.pending() is None
    m.restore(result["rollback"])
    assert m._fingerprint(m.main) == changed
    m.drop("before")
    assert "before" not in [entry["name"] for entry in m.list()]
    with pytest.raises(NotFoundInGraph):
        m.restore("before")


@pytest.mark.parametrize("command,after,occurrence", [("GRAPH.COPY", False, 1), ("GRAPH.COPY", True, 1),
    ("GRAPH.COPY", False, 2), ("GRAPH.COPY", True, 2), ("RENAME", False, 1), ("RENAME", True, 1)])
def test_failure_is_recoverable_with_new_manager(snapshots, monkeypatch, command, after, occurrence):
    m = snapshots
    m.create("before")
    expected = m._fingerprint(m.main)
    add_later(m)
    changed = m._fingerprint(m.main)
    durable = m._durable
    fired = False
    seen = 0

    def fail(*args):
        nonlocal fired, seen
        if args[0] == command:
            seen += 1
        if args[0] == command and not fired and seen == occurrence:
            fired = True
            if after:
                durable(*args)
            raise Unavailable("injected lost connection")
        return durable(*args)

    monkeypatch.setattr(m, "_durable", fail)
    with pytest.raises(Unavailable):
        m.restore("before")
    assert m.pending()
    assert m._fingerprint(m.main) in {expected, changed}
    fresh = Checkpoints(m.db, m.tenant)
    with pytest.raises(Conflict):
        fresh.create("blocked")
    result = fresh.recover()
    assert fresh._fingerprint(fresh.main) == expected
    assert fresh._fingerprint(checkpoint_graph_name(m.tenant, result["rollback"])) == changed


def test_explicit_rollback_after_rename_ack_loss(snapshots, monkeypatch):
    m = snapshots
    m.create("before")
    add_later(m)
    expected = m._fingerprint(m.main)
    durable = m._durable

    def fail(*args):
        result = durable(*args)
        if args[0] == "RENAME":
            raise Unavailable("lost acknowledgement")
        return result

    monkeypatch.setattr(m, "_durable", fail)
    with pytest.raises(Unavailable):
        m.restore("before")
    Checkpoints(m.db, m.tenant).recover(rollback=True)
    assert m._fingerprint(m.main) == expected


def test_killed_process_journal_resumes(snapshots):
    m = snapshots
    m.create("before")
    expected = m._fingerprint(m.main)
    add_later(m)
    script = """
import os,sys
from pedigree.db.client import Db
from pedigree.engine.checkpoint import Checkpoints
m=Checkpoints(Db(),sys.argv[1])
durable=m._durable
def die(*args):
    result=durable(*args)
    if args[0]=='RENAME': os._exit(47)
    return result
m._durable=die
m.restore('before')
"""
    result = subprocess.run([sys.executable, "-c", script, m.tenant],
                            env=os.environ.copy(), capture_output=True, timeout=60)
    assert result.returncode == 47, result.stderr.decode()
    assert m.pending()["op"] == "restore"
    Checkpoints(m.db, m.tenant).recover()
    assert m._fingerprint(m.main) == expected
    assert m.pending() is None


def test_create_ack_loss_and_drop_recover(snapshots, monkeypatch):
    m = snapshots
    durable = m._durable

    def fail(*args):
        result = durable(*args)
        if args[0] == "GRAPH.COPY":
            raise Unavailable("lost copy acknowledgement")
        return result

    monkeypatch.setattr(m, "_durable", fail)
    with pytest.raises(Unavailable):
        m.create("saved")
    Checkpoints(m.db, m.tenant).recover()
    assert m.list()[0]["name"] == "saved"


def test_limits_and_tenant_listing(snapshots, monkeypatch):
    m = snapshots
    m.create("mine")
    foreign = Checkpoints(m.db, "foreign" + uuid.uuid4().hex[:8])
    assert foreign.list() == []
    monkeypatch.setattr("pedigree.engine.checkpoint.MAX_CHECKPOINTS", 1)
    with pytest.raises(Conflict):
        m.create("too-many")
    with pytest.raises(Conflict):
        m.restore("mine")
    assert m.pending() is None
    with pytest.raises(NotFoundInGraph):
        m.restore("missing")


def test_restore_repairs_unhealthy_live_graph_and_preserves_its_backup(snapshots):
    m = snapshots
    m.create("healthy")
    original = m._fingerprint(m.main)
    m.db.query(m.main, "MATCH(n:Node {id:$id}) SET n.status=$status",
               {"id": "original", "status": "invalid-status"})
    damaged = m._fingerprint(m.main)
    result = m.restore("healthy")
    assert m._fingerprint(m.main) == original
    assert m._fingerprint(checkpoint_graph_name(m.tenant, result["rollback"])) == damaged


def test_stranded_mutex_requires_explicit_confirmation(snapshots):
    from pedigree.engine.quota import lock_key

    m = snapshots
    key = lock_key(m.main)
    foreign_key = lock_key("ped:foreign" + uuid.uuid4().hex[:8])
    m.connection.set(key, "stopped-owner")
    m.connection.set(foreign_key, "foreign-owner")
    try:
        assert m.mutex_status() == {"held": True}
        with pytest.raises(InvalidArgument):
            m.release_mutex()
        assert m.mutex_status() == {"held": True}
        assert m.release_mutex(confirmed=True) == {"released": True, "held": False}
        assert m.connection.get(foreign_key) == "foreign-owner"
        assert m.release_mutex(confirmed=True) == {"released": False, "held": False}
    finally:
        m.connection.delete(key, foreign_key)


@pytest.mark.parametrize("failure", [None, "before", "after"])
def test_restore_missing_main_and_safe_recovery(snapshots, monkeypatch, failure):
    m = snapshots
    m.create("disaster")
    expected = m._fingerprint(m.main)
    m.db.select(m.main).delete()
    monkeypatch.setattr("pedigree.engine.checkpoint.MAX_CHECKPOINTS", 1)
    if failure:
        durable = m._durable

        def fail(*args):
            if args[0] == "RENAME":
                if failure == "after":
                    durable(*args)
                raise Unavailable("injected rename failure")
            return durable(*args)

        monkeypatch.setattr(m, "_durable", fail)
        with pytest.raises(Unavailable):
            m.restore("disaster")
        fresh = Checkpoints(m.db, m.tenant)
        with pytest.raises(InvalidArgument, match="no previous main graph"):
            fresh.recover(rollback=True)
        assert fresh.pending()["before"] is None
        fresh.recover()
    else:
        assert m.restore("disaster")["rollback"] is None
    assert m._fingerprint(m.main) == expected
    assert m.pending() is None


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789./:* ", min_size=1, max_size=45))
@settings(max_examples=50)
def test_name_validation_is_namespace_boundary(name):
    try:
        graph = checkpoint_graph_name("tenantabc", name)
    except InvalidArgument:
        return
    assert graph.startswith("ped:tenantabc:ck:")
    assert ":" not in name and "/" not in name and len(name) <= 32


def test_rollback_choice_survives_another_interruption(snapshots, monkeypatch):
    m = snapshots
    m.create("before")
    add_later(m)
    previous = m._fingerprint(m.main)
    durable = m._durable

    def fail(*args):
        result = durable(*args)
        if args[0] == "RENAME":
            raise Unavailable("lost rename acknowledgement")
        return result

    monkeypatch.setattr(m, "_durable", fail)
    with pytest.raises(Unavailable):
        m.restore("before")
    with pytest.raises(Unavailable):
        m.recover(rollback=True)
    Checkpoints(m.db, m.tenant).recover()
    assert m._fingerprint(m.main) == previous


@pytest.mark.skipif(not os.getenv("PEDIGREE_CHECKPOINT_RESTART_CONTAINER"),
                    reason="requires an explicitly owned restartable database container")
@pytest.mark.parametrize("crash_point", ["before", "after"])
def test_aof_journal_survives_database_crash(snapshots, monkeypatch, crash_point):
    import time

    m = snapshots
    m.create("durable")
    expected = m._fingerprint(m.main)
    add_later(m)
    previous = m._fingerprint(m.main)
    durable = m._durable

    def interrupt(*args):
        if args[0] == "RENAME":
            if crash_point == "after":
                durable(*args)
            raise Unavailable("interrupted around replacement")
        return durable(*args)

    monkeypatch.setattr(m, "_durable", interrupt)
    with pytest.raises(Unavailable):
        m.restore("durable")
    pending = m.pending()
    container = os.environ["PEDIGREE_CHECKPOINT_RESTART_CONTAINER"]
    assert container == "pedigree-checkpoint-db-6386"
    assert m.db.settings.falkor_port == 6386
    subprocess.run(["docker", "kill", container], check=True, capture_output=True, timeout=30)
    subprocess.run(["docker", "start", container], check=True, capture_output=True, timeout=30)
    m.db.reset()
    for _ in range(100):
        if m.db.ping():
            break
        time.sleep(0.1)
    fresh = Checkpoints(m.db, m.tenant)
    assert fresh.pending() == pending
    assert fresh._fingerprint(fresh.main) == (previous if crash_point == "before" else expected)
    result = fresh.recover()
    assert fresh._fingerprint(fresh.main) == expected
    assert fresh._fingerprint(checkpoint_graph_name(m.tenant, result["rollback"])) == previous
    assert fresh.pending() is None


def test_capture_receipts_rewind_with_graph(snapshots):
    from pedigree.db import queries as Q

    m = snapshots
    params = {"id": "capture_fixture", "digest": "a" * 64,
              "tenant": m.tenant, "now": 1}
    m.db.query(m.main, Q.Q_CAPTURE_CREATE, params)
    m.create("receipt")
    m.db.query(m.main, Q.Q_CAPTURE_ADVANCE,
               {"id": params["id"], "cursor": 4, "aliases": "{}", "created": "[]", "plans": "{}"})
    result = m.restore("receipt")
    assert m.db.ro_query(m.main, Q.Q_CAPTURE_GET, params).result_set[0][1] == 0
    backup = checkpoint_graph_name(m.tenant, result["rollback"])
    assert m.db.ro_query(backup, Q.Q_CAPTURE_GET, params).result_set[0][1] == 4


def test_rejected_unhealthy_rollback_does_not_poison_forward_recovery(snapshots, monkeypatch):
    m = snapshots
    m.create("healthy")
    expected = m._fingerprint(m.main)
    m.db.query(m.main, "MATCH(n:Node {id:$id}) SET n.status=$status",
               {"id": "original", "status": "invalid-status"})
    durable = m._durable

    def interrupt(*args):
        result = durable(*args)
        if args[0] == "RENAME":
            raise Unavailable("lost replacement acknowledgement")
        return result

    monkeypatch.setattr(m, "_durable", interrupt)
    with pytest.raises(Unavailable):
        m.restore("healthy")
    fresh = Checkpoints(m.db, m.tenant)
    with pytest.raises(Conflict, match="invariants"):
        fresh.recover(rollback=True)
    assert not fresh.pending().get("recover_previous", False)
    fresh.recover()
    assert fresh._fingerprint(fresh.main) == expected
