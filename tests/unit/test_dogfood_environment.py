"""The harness must exercise the selected DB, never an implicit default listener."""
import importlib.util
import sys
from pathlib import Path


def test_child_database_selection_survives_environment_sanitization(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/dogfood.py"
    spec = importlib.util.spec_from_file_location("dogfood_environment_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setenv("FALKOR_HOST", "127.0.0.2")
    monkeypatch.setenv("FALKOR_PORT", "16381")
    monkeypatch.setenv("FALKOR_USERNAME", "harness-user")
    monkeypatch.setenv("FALKOR_PASSWORD", "example-harness-password")
    monkeypatch.setenv("PEDIGREE_SEED_DEMO", "1")
    monkeypatch.setenv("PEDIGREE_TOKEN", "example-unrelated-agent")
    try:
        env = module.child_environment()
        assert env["FALKOR_HOST"] == "127.0.0.2"
        assert env["FALKOR_PORT"] == "16381"
        assert env["FALKOR_USERNAME"] == "harness-user"
        assert env["FALKOR_PASSWORD"] == "example-harness-password"
        assert "PEDIGREE_SEED_DEMO" not in env
        assert "PEDIGREE_TOKEN" not in env
    finally:
        del sys.modules[spec.name]
