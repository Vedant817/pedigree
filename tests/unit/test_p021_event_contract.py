import pytest

from pedigree.adapters import normalize_event, normalize_events
from pedigree.errors import InvalidArgument


@pytest.mark.parametrize('raw', [
    {'type': 'source', 'kind': []},
    {'type': 'source', 'kind': {'x': 1}},
    {'type': 'source', 'kind': 'source'},
    {'kind': 'source_read', 'uri': 'u'},
])
def test_source_operation_discriminator_is_valid_without_source_kind(raw):
    if isinstance(raw.get('kind'), str):
        result = normalize_event('generic', raw)
        assert result['kind'] == 'web'
    else:
        with pytest.raises(InvalidArgument):
            normalize_event('generic', raw)

@pytest.mark.parametrize('events', [5, 'text', {}, [5], [None], [[]]])
def test_wrong_event_containers_raise_typed_error(events):
    with pytest.raises(InvalidArgument):
        normalize_events('generic', {'events': events})


def test_aliases_null_producer_fields_and_unknown_runtime_preserved():
    out = normalize_events('future-runtime', {'session_id': 's', 'events': [
        {'kind': 'ensure_session'},
        {'type': 'source_read', 'source_kind': 'file', 'uri': 'a', 'conf': None},
        {'type': 'tool_use', 'tool_name': 'Read', 'title': 'ok\nwith\ttabs', 'memories': None, 'artifacts': None},
    ]})
    assert [event['op'] for event in out] == ['session', 'source', 'action']
    assert all(event['session_id'] == 's' for event in out)
    assert out[1]['kind'] == 'file'
    assert out[2]['tool'] == 'Read'
    assert out[2]['summary'] == 'ok\nwith\ttabs'

@pytest.mark.parametrize('field,value', [
    ('uri', 'identity\nchanged'), ('title', 'title\tvalue'),
    ('id', 'id\n'), ('content_hash', 'not-a-hash'),
    ('conf', [True]), ('source_kind', ['web']),
])
def test_source_identity_and_classification_fields_reject_without_repair(field, value):
    with pytest.raises(InvalidArgument):
        normalize_event('generic', {'type': 'source', field: value})


def test_scanner_event_rejected_before_operator_batch_can_mutate():
    with pytest.raises(InvalidArgument):
        normalize_events('generic', {'events': [
            {'type': 'memory', 'text': 'valid early'},
            {'type': 'source', 'kind': 'scanner'},
        ]})


@pytest.mark.parametrize('name,arguments', [
    ('pedigree_record_source', {'uri': 'bad\x7furi'}),
    ('pedigree_record_source', {'kind': 'not-a-kind'}),
    ('pedigree_remember', {'derived_from': 'scalar'}),
    ('pedigree_remember', {'text': 'bad\x00text'}),
    ('pedigree_record_action', {'tool': 'Bash', 'artifacts': [5]}),
    ('pedigree_record_action', {'tool': 'Bash', 'unknown': 'ignored'}),
    ('pedigree_check_action', {'tool': 'Bash', 'record': 1}),
    ('pedigree_audit_sources', {'limit': True}),
    ('pedigree_blame', {'node_id': 'good', 'max_depth': '12'}),
])
def test_mcp_shared_contract_is_strict(name, arguments):
    from pedigree.validation import validate_tool_arguments
    with pytest.raises(InvalidArgument):
        validate_tool_arguments(name, arguments)
