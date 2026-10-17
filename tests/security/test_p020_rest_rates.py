"""Real DB REST admission boundaries, with exact fixture ownership."""
import pytest
from fastapi.testclient import TestClient

from pedigree.api.app import create_app
from pedigree.config import Settings


@pytest.fixture
def rates(fresh_graph):
    db, tenant, graph = fresh_graph
    app = create_app(db, Settings(_env_file=None, pedigree_admin_token='rate-test-admin'))
    credential = app.state.registry.create_tenant(tenant)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield db, graph, app, client, credential
    finally:
        db.query(app.state.registry.gname, 'MATCH(t:Tenant {id:$id}) DELETE t', {'id': tenant})


def headers(credential):
    return {'Authorization': 'Bearer ' + credential.agent_token}


def test_exact_120_writes_then_rate_limit(rates):
    _, _, _, client, credential = rates
    outcomes = [client.post('/v1/sources', headers=headers(credential),
                json={'kind': 'web', 'uri': 'rate-same-source'}).status_code for _ in range(121)]
    assert outcomes == [200] * 120 + [429]


def test_reads_do_not_consume_write_budget(rates):
    _, _, _, client, credential = rates
    assert all(client.get('/v1/stats', headers=headers(credential)).status_code == 200 for _ in range(120))
    result = client.post('/v1/sources', headers=headers(credential), json={'kind': 'web', 'uri': 'after-reads'})
    assert result.status_code == 200


def test_permission_and_shape_rejections_do_not_charge(rates):
    _, _, app, client, credential = rates
    app.state.limiter.write_limit = 1
    for payload, status in [({'kind': 'human'}, 403), ({'kind': 'web', 'uri': 'bad\x00uri'}, 422)]:
        assert client.post('/v1/sources', headers=headers(credential), json=payload).status_code == status
    assert client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'}).status_code == 200
    blocked = client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'})
    assert blocked.status_code == 429
    assert int(blocked.headers['Retry-After']) >= 1


def test_admitted_engine_failure_counts_once(rates):
    _, _, app, client, credential = rates
    app.state.limiter.write_limit = 1
    assert client.post('/v1/memories', headers=headers(credential),
                       json={'derived_from': ['missing']}).status_code == 404
    assert client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'}).status_code == 429
    assert client.get('/v1/stats', headers=headers(credential)).status_code == 200


def test_events_batch_is_one_admission_and_bad_tail_is_not_admitted(rates):
    _, _, app, client, credential = rates
    app.state.limiter.write_limit = 1
    assert client.post('/v1/events', headers=headers(credential), json={'events': [
        {'type': 'memory'}, {'type': 'unknown'}]}).status_code == 422
    response = client.post('/v1/events', headers=headers(credential), json={'events': [
        {'type': 'memory'}, {'type': 'memory'}]})
    assert response.status_code == 200
    assert len(response.json()['created']) == 2
    assert client.post('/v1/events', headers=headers(credential), json={'events': []}).status_code == 429


def test_gate_read_and_whatif_write_classification(rates):
    _, _, app, client, credential = rates
    app.state.limiter.read_limit = app.state.limiter.write_limit = 1
    assert client.post('/v1/gate', headers=headers(credential),
                       json={'action': {'tool': 'Read'}}).status_code == 200
    assert client.get('/v1/stats', headers=headers(credential)).status_code == 429
    assert client.post('/v1/whatif', headers=headers(credential), json={'roots': ['missing']}).status_code == 404
    assert client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'}).status_code == 429


def test_dry_run_uses_read_and_destructive_buckets(rates):
    _, _, app, client, credential = rates
    app.state.limiter.read_limit = app.state.limiter.write_limit = app.state.limiter.destructive_limit = 1
    operator = {'Authorization': 'Bearer ' + credential.operator_token}
    assert client.post('/v1/revoke', headers=operator, json={'root_id': 'missing', 'dry_run': True}).status_code == 404
    assert client.get('/v1/stats', headers=headers(credential)).status_code == 429
    assert client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'}).status_code == 200
    assert client.post('/v1/reinstate', headers=operator, json={'root_id': 'missing', 'dry_run': True}).status_code == 429


def test_failed_auth_backoff_ignores_forwarded_headers_and_blocks_shared_peer(rates):
    _, _, app, client, credential = rates
    now = [0.0]
    app.state.limiter.clock = lambda: now[0]
    for index in range(10):
        response = client.get('/v1/stats', headers={'Authorization': 'Bearer invalid',
                    'X-Forwarded-For': str(index), 'Forwarded': 'for=' + str(index)})
        assert response.status_code == 401
    blocked = client.get('/v1/stats', headers=headers(credential))
    assert blocked.status_code == 429
    assert blocked.headers['Retry-After'] == '60'
    now[0] = 60.0
    assert client.get('/v1/stats', headers=headers(credential)).status_code == 200


def test_admin_and_metrics_share_failed_peer_backoff(rates):
    _, _, _, client, _ = rates
    for index in range(10):
        assert client.get('/admin/tenants' if index % 2 else '/metrics').status_code == 401
    response = client.get('/metrics', headers={'X-Admin-Token': 'rate-test-admin'})
    assert response.status_code == 429
    assert int(response.headers['Retry-After']) >= 1


def test_invalid_read_parameters_do_not_consume_read_admission(rates):
    _, _, app, client, credential = rates
    app.state.limiter.read_limit = 1
    for path in ('/v1/blame/bad%20id', '/v1/audit/sources?limit=invalid', '/v1/impact/valid?max_depth=13'):
        response = client.get(path, headers=headers(credential))
        assert response.status_code == 422
    assert client.get('/v1/stats', headers=headers(credential)).status_code == 200


def test_unsupported_operator_source_rejects_before_schema_and_admission(rates, monkeypatch):
    from pedigree.api import auth
    _, _, app, client, credential = rates
    app.state.limiter.write_limit = 1
    calls = []
    original = auth.ensure_schema
    def observed_schema(db, graph):
        calls.append(graph)
        return original(db, graph)
    monkeypatch.setattr(auth, 'ensure_schema', observed_schema)
    operator = {'Authorization': 'Bearer ' + credential.operator_token}
    response = client.post('/v1/sources', headers=operator, json={'kind': 'scanner'})
    assert response.status_code == 422
    response = client.post('/v1/sources', headers=headers(credential), json={'kind': 'scanner'})
    assert response.status_code == 403
    assert calls == []
    response = client.post('/v1/sources', headers=operator, json={'kind': 'web'})
    assert response.status_code == 200
    assert len(calls) == 1
    response = client.post('/v1/sources', headers=headers(credential), json={'kind': 'web'})
    assert response.status_code == 429
    assert len(calls) == 1
