"""Credential delivery and explicit role migration; no real bearer values are logged."""

import json
from types import SimpleNamespace

import pytest

from pedigree import cli
from pedigree.config import Settings
from pedigree.errors import Conflict


@pytest.fixture
def registry(monkeypatch):
    credential = SimpleNamespace(tenant_id="rolefixture", token="test-agent",
                                 agent_token="test-agent", operator_token="test-operator")
    registry = SimpleNamespace(create_tenant=lambda *args: credential)
    monkeypatch.setattr("pedigree.api.registry.TenantRegistry", lambda *args: registry)
    monkeypatch.setattr("pedigree.db.client.Db", lambda *args: object())
    return registry


def test_admin_creation_delivers_named_roles_and_agent_alias(registry, capsys):
    assert cli.admin_create_tenant(Settings(_env_file=None, pedigree_env="dev"),
                                   "rolefixture", None) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["token"] == payload["agent_token"] == "test-agent"
    assert payload["operator_token"] == "test-operator"


@pytest.mark.parametrize("rotate", [False, True])
def test_admin_issue_operator_is_explicit_and_never_returns_agent(registry, monkeypatch, capsys, rotate):
    calls = []

    def issue(tenant, *, rotate):
        calls.append((tenant, rotate))
        return "test-issued-operator"

    registry.issue_operator = issue
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, pedigree_env="dev"))
    args = ["admin", "issue-operator", "--id", "rolefixture"] + (["--rotate"] if rotate else [])
    assert cli.main(args) == 0
    assert calls == [("rolefixture", rotate)]
    assert json.loads(capsys.readouterr().out) == {
        "tenant": "rolefixture", "operator_token": "test-issued-operator"}


def test_admin_operator_conflict_emits_no_credential(registry, capsys):
    def fail(*args, **kwargs):
        raise Conflict("operator already issued")

    registry.issue_operator = fail
    assert cli.admin_issue_operator(Settings(_env_file=None, pedigree_env="dev"),
                                    "rolefixture", False) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "conflict" in captured.err


def test_operator_issuance_requires_production_admin_configuration(registry, capsys):
    registry.issue_operator = lambda *args, **kwargs: pytest.fail("must refuse before issuance")
    assert cli.admin_issue_operator(Settings(_env_file=None, pedigree_env="production",
                                             pedigree_admin_token=""), "rolefixture") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refusing" in captured.err
