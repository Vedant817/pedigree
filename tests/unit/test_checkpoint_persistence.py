from types import SimpleNamespace

import pytest

from pedigree.engine.checkpoint import Checkpoints
from pedigree.errors import Unavailable


def test_fsync_failure_is_not_success():
    class Pipeline:
        commands = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute_command(self, *command):
            self.commands.append(command)

        def execute(self):
            return [True, [0, 0]]

    pipe = Pipeline()

    def pipeline(*, transaction):
        assert transaction is False
        return pipe

    db = SimpleNamespace(client=SimpleNamespace(connection=SimpleNamespace(pipeline=pipeline)))
    manager = Checkpoints(db, "tenantabc")
    with pytest.raises(Unavailable, match="persistence not confirmed"):
        manager._durable("SET", manager.key, "pending", "NX")
    assert pipe.commands == [("SET", manager.key, "pending", "NX"), ("WAITAOF", 1, 0, 5000)]


def test_compaction_failure_is_not_ready():
    from redis.exceptions import ResponseError

    def fail():
        raise ResponseError("injected rewrite failure")

    connection = SimpleNamespace(
        info=lambda _section: {"aof_enabled": 1, "aof_rewrites": 0},
        bgrewriteaof=fail,
    )
    manager = Checkpoints(SimpleNamespace(client=SimpleNamespace(connection=connection)), "tenantabc")
    with pytest.raises(Unavailable, match="compaction unavailable"):
        manager._ready()


def test_aof_is_mandatory_before_compaction():
    connection = SimpleNamespace(info=lambda _section: {"aof_enabled": 0})
    manager = Checkpoints(SimpleNamespace(client=SimpleNamespace(connection=connection)), "tenantabc")
    with pytest.raises(Unavailable, match="requires AOF persistence"):
        manager._ready()
