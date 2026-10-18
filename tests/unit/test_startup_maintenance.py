"""Startup repair must not interleave with a live lifecycle operation."""
import threading
from types import SimpleNamespace

from pedigree.api.app import _startup_resume
from pedigree.engine.revoke import tenant_lock


def test_startup_repair_waits_for_tenant_lifecycle_lock(monkeypatch):
    selected, repairing = threading.Event(), threading.Event()
    def scoped(tenant):
        selected.set()
        return object()
    def resume(*args):
        repairing.set()
        return []
    monkeypatch.setattr("pedigree.engine.revoke.resume_incomplete", resume)
    monkeypatch.setattr("pedigree.engine.revoke.reconcile", lambda *args: {})
    db = SimpleNamespace(for_tenant=scoped)
    registry = SimpleNamespace(list_tenants=lambda: [SimpleNamespace(tenant_id="racefixture")])
    thread = threading.Thread(target=_startup_resume, args=(db, registry))
    try:
        with tenant_lock("racefixture"):
            thread.start()
            assert selected.wait(2)
            assert not repairing.wait(.1), "startup repair overlapped an active lifecycle mutation"
        thread.join(2)
        assert repairing.is_set()
        assert not thread.is_alive()
    finally:
        thread.join(2)
