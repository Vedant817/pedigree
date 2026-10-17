"""Runtime setup boundaries, using real HTTP admission and credential files."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import Settings


def seed_module():
    path = Path(__file__).resolve().parents[2] / 'scripts/seed_demo.py'
    spec = importlib.util.spec_from_file_location('runtime_seed', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_denies_deployment_admin_even_with_correct_token(fresh_graph):
    db, _, _ = fresh_graph
    app = create_app(db, Settings(_env_file=None, pedigree_seed_demo=True,
                                 pedigree_admin_token='runtime-test-admin'))
    with TestClient(app) as client:
        for method, route, payload in [
            ('GET', '/admin/tenants', None),
            ('POST', '/admin/tenants', {'id': 'runtimedemonew'}),
            ('POST', '/v1/admin/resume', {'tenant': 'runtimedemonew'}),
        ]:
            assert client.request(method, route, json=payload,
                headers={'X-Admin-Token': 'runtime-test-admin'}).status_code == 403


def test_seed_boot_fails_if_existing_tenant_has_no_local_credential(monkeypatch, tmp_path, capsys):
    module = seed_module()
    monkeypatch.setenv('PEDIGREE_CREDENTIALS_DIR', str(tmp_path))
    monkeypatch.setattr(module, 'Db', lambda: object())
    monkeypatch.setattr(module, 'TenantRegistry', lambda db: SimpleNamespace())
    monkeypatch.setattr(module, 'ensure_demo_tenant', lambda *args: None)
    monkeypatch.setattr(module, 'seed_scenarios', lambda *args: pytest.fail('must fail before seed'))
    assert module.main() == 1
    err = capsys.readouterr().err
    assert 'restore the private file' in err and 'dedicated' in err
    assert 'token' not in err.lower()  # never echo credential material


def test_seed_refuses_revoked_demo_tenant_with_actionable_error(tmp_path):
    module = seed_module()
    registry = SimpleNamespace(get_record=lambda tenant: SimpleNamespace(status='revoked'))
    with pytest.raises(module.SeedError):
        module.ensure_demo_tenant(registry, 'demo', tmp_path)


def test_seed_boot_uses_configured_durable_credentials_directory(monkeypatch, tmp_path):
    module = seed_module()
    monkeypatch.setenv('PEDIGREE_CREDENTIALS_DIR', str(tmp_path))
    monkeypatch.setattr(module, 'Db', lambda: object())
    monkeypatch.setattr(module, 'TenantRegistry', lambda db: SimpleNamespace())
    calls = []
    def ensure(registry, tenant, directory):
        calls.append(directory)
        return directory / 'demo-demo.json'
    monkeypatch.setattr(module, 'ensure_demo_tenant', ensure)
    monkeypatch.setattr(module, 'seed_scenarios', lambda *args: {'created': 0})
    assert module.main() == 0
    assert calls == [tmp_path]

@pytest.mark.parametrize('version,expected', [(42201, 200), (42200, 503), (None, 503)])
def test_readiness_requires_pinned_module(version, expected):
    from fastapi import FastAPI

    from pedigree.api.app import _register_error_handlers
    from pedigree.api.routes.health import register
    app = FastAPI()
    _register_error_handlers(app)
    register(app, SimpleNamespace(ping=lambda: True, module_version=lambda: version))
    with TestClient(app) as client:
        assert client.get('/readyz').status_code == expected


def runtime_module():
    path = Path(__file__).resolve().parents[2] / 'scripts/runtime.py'
    spec = importlib.util.spec_from_file_location('runtime_script', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Connection:
    def __init__(self, reply):
        self.reply = reply

    def execute_command(self, *args):
        return self.reply


@pytest.mark.parametrize('reply,expected', [
    (['TIMEOUT_MAX', 60000], 60000),           # flat reply from falkordb/falkordb:v4.22.1
    ([['TIMEOUT_MAX', 60000]], 60000),         # nested reply shape
])
def test_config_value_accepts_flat_and_nested_replies(reply, expected):
    module = runtime_module()
    db = SimpleNamespace(client=SimpleNamespace(connection=_Connection(reply)))
    assert module.config_value(db, 'TIMEOUT_MAX') == expected


@pytest.mark.parametrize('reply', [
    ['OTHER_LIMIT', 60000], [['TIMEOUT_MAX', 'nan']], [['TIMEOUT_MAX']], [], None,
])
def test_config_value_rejects_mismatched_or_malformed_replies(reply):
    module = runtime_module()
    db = SimpleNamespace(client=SimpleNamespace(connection=_Connection(reply)))
    with pytest.raises(RuntimeError):
        module.config_value(db, 'TIMEOUT_MAX')


def _ldd(stdout):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=1)


def test_module_dependencies_reports_missing_libraries(monkeypatch, tmp_path):
    module = runtime_module()
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/usr/bin/ldd')
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: _ldd(
        '\tlinux-vdso.so.1 (0x00007fff)\n'
        '\tlibgomp.so.1 => not found\n'
        '\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f)\n'))
    assert module.module_dependencies(tmp_path / 'module.so') == ['libgomp.so.1']


def test_module_dependencies_absent_ldd_or_clean_output(monkeypatch, tmp_path):
    module = runtime_module()
    monkeypatch.setattr(module.shutil, 'which', lambda name: None)
    assert module.module_dependencies(tmp_path / 'module.so') == []
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/usr/bin/ldd')
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: _ldd(
        '\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f)\n'))
    assert module.module_dependencies(tmp_path / 'module.so') == []


def test_runtime_failure_prints_the_authored_message(monkeypatch, capsys):
    module = runtime_module()
    monkeypatch.setattr(module.sys, 'argv', ['runtime.py', 'db'])

    def boom():
        raise RuntimeError('pinned module needs missing system libraries: libgomp.so.1')

    monkeypatch.setattr(module, 'run_db', boom)
    assert module.main() == 1
    assert 'libgomp.so.1' in capsys.readouterr().err
