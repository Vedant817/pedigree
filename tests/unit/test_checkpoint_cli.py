from argparse import Namespace

from pedigree.cli import checkpoint_command
from pedigree.config import Settings


def test_checkpoint_requires_admin_without_touching_db(capsys):
    args = Namespace(action="list", tenant="tenantabc", writers_stopped=False)
    assert checkpoint_command(Settings(_env_file=None, pedigree_admin_token=""), args) == 1
    assert "deployment administrator credential required" in capsys.readouterr().err


def test_checkpoint_requires_quiescence_without_touching_db(capsys):
    args = Namespace(action="restore", tenant="tenantabc", writers_stopped=False)
    settings = Settings(_env_file=None, pedigree_admin_token="local-recovery-test-credential")
    assert checkpoint_command(settings, args) == 1
    assert "stop every API/MCP/direct writer" in capsys.readouterr().err
