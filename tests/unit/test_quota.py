"""Coordination contract tests; public path behavior is exercised on real FalkorDB."""

from types import SimpleNamespace

import pytest

from pedigree.engine.quota import QuotaPolicy, admission, lock_key
from pedigree.errors import InvalidArgument, Unavailable


class Connection:
    def __init__(self):
        self.owner = None
        self.set_options = []

    def set(self, key, value, **kwargs):
        self.set_options.append(kwargs)
        if self.owner is not None:
            return False
        self.owner = value
        return True

    def get(self, key):
        return self.owner

    def eval(self, script, count, key, token):
        if self.owner != token:
            return 0
        self.owner = None
        return 1


def make_db():
    connection = Connection()
    calls = []
    db = SimpleNamespace(
        client=SimpleNamespace(connection=connection), query=lambda *a, **kw: calls.append(a)
    )
    return db, connection, calls


def test_nonexpiring_owner_only_release():
    db, connection, calls = make_db()
    policy = QuotaPolicy("tenant", 1)
    with pytest.raises(Unavailable, match="ownership lost"):
        with admission(db, "ped:tenant", policy):
            connection.owner = "a-different-owner"
    assert connection.owner == "a-different-owner"
    assert connection.set_options == [{"nx": True}]
    assert not calls


def test_known_owner_loss_blocks_mutation():
    db, connection, calls = make_db()
    with pytest.raises(Unavailable, match="ownership lost"):
        with admission(db, "ped:tenant", QuotaPolicy("tenant", 1)) as locked:
            connection.owner = "replacement-owner"
            locked.query("ped:tenant", "unused")
    assert not calls
    assert connection.owner == "replacement-owner"


def test_nested_reuses_one_owner_and_releases_once():
    db, connection, _ = make_db()
    policy = QuotaPolicy("tenant", 1)
    with admission(db, "ped:tenant", policy) as first:
        with admission(db, "ped:tenant", policy) as second:
            assert first is second
        assert connection.owner is not None
    assert connection.owner is None
    assert len(connection.set_options) == 1


def test_policy_graph_mismatch_fails_before_lock():
    db, connection, _ = make_db()
    with pytest.raises(InvalidArgument):
        with admission(db, "ped:other", QuotaPolicy("tenant", 1)):
            pytest.fail("policy mismatch admitted")
    assert not connection.set_options
    assert lock_key("ped:tenant") != lock_key("other:tenant")


def test_coordinator_failure_is_fail_closed():
    db, connection, calls = make_db()

    def unavailable(*args, **kwargs):
        raise OSError("synthetic network failure")

    connection.set = unavailable
    with pytest.raises(Unavailable, match="coordination unavailable"):
        with admission(db, "ped:tenant", QuotaPolicy("tenant", 1)):
            pytest.fail("coordinator failure admitted")
    assert not calls
