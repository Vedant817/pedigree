"""Production must be empty by default and use durable authenticated storage."""
from pathlib import Path

import pytest
import yaml

from pedigree.config import Settings, admin_token_problem

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("flag", ["pedigree_seed_demo", "pedigree_demo_login"])
def test_production_refuses_demo_flags(flag):
    settings = Settings(_env_file=None, pedigree_env="production",
                        pedigree_admin_token="launch-test-private-admin", **{flag: True})
    assert "demo" in (admin_token_problem(settings) or "").lower()


def test_default_compose_has_no_seed_and_requires_credentials():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    api = compose["services"]["pedigree"]
    env = api["environment"]
    assert env["PEDIGREE_SEED_DEMO"] == "0"
    assert env["PEDIGREE_DEMO_LOGIN"] == "0"
    for name in ("PEDIGREE_ADMIN_TOKEN", "PEDIGREE_SECRET", "FALKOR_PASSWORD"):
        assert ":?" in env[name]
    db = compose["services"]["db"]
    assert "--appendonly yes" in db["environment"]["REDIS_ARGS"]
    assert "--requirepass" in db["environment"]["REDIS_ARGS"]
    assert db["volumes"] and api["volumes"]


def test_render_database_is_durable_and_api_does_not_sleep():
    services = {s["name"]: s for s in yaml.safe_load((ROOT / "render.yaml").read_text())["services"]}
    db, api = services["pedigree-db"], services["pedigree-api"]
    assert db["disk"]["mountPath"] == "/var/lib/falkordb/data"
    assert db["disk"]["sizeGB"] == 1
    assert api["plan"] != "free"
    env = {e["key"]: e for e in db["envVars"]}
    assert "--appendonly yes" in env["REDIS_ARGS"]["value"]


def test_settings_repr_omits_credentials():
    settings = Settings(_env_file=None, falkor_password="database-private-value",
                        pedigree_admin_token="admin-private-value", pedigree_secret="hmac-private-value",
                        gemini_api_key="provider-private-value", groq_api_key="other-private-value")
    assert "private-value" not in repr(settings)
