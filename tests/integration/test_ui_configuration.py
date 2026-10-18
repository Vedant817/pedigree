"""The public workspace advertises only configured capabilities."""
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import Settings


def test_production_ui_has_no_demo_or_dead_docs_link(fresh_graph):
    db, _, _ = fresh_graph
    settings = Settings(_env_file=None, pedigree_env="production", pedigree_admin_token="ui-config-test-admin")
    with TestClient(create_app(db, settings)) as client:
        result = client.get("/v1/ui/config")
        assert result.status_code == 200
        assert result.json() == {"demo_login": False, "api_docs": False}
        assert result.headers["cache-control"] == "no-store"
        html = client.get("/").text
        assert 'id="demo-login" class="quiet" hidden' in html
        assert 'id="api-reference" href="/docs" hidden' in html


def test_local_configuration_can_explicitly_expose_demo(fresh_graph):
    db, _, _ = fresh_graph
    settings = Settings(_env_file=None, pedigree_env="local", pedigree_demo_login=True)
    with TestClient(create_app(db, settings)) as client:
        assert client.get("/v1/ui/config").json() == {"demo_login": True, "api_docs": True}
