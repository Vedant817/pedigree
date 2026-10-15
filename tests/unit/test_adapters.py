"""Unit tests for the F-07 event normaliser (audit finding: source-kind fidelity).

Regression tests for the F-07 capture audit: `source_kind`/`kind` confusion silently
mislabelled (or dropped) Sources coming from hooks.
"""
from __future__ import annotations

from pedigree.adapters import normalize_event, normalize_events


def test_source_kind_wins_over_kind():
    spec = normalize_event("generic", {"type": "source", "source_kind": "rules_file", "kind": "web",
                                       "uri": "CLAUDE.md"})
    assert spec is not None
    assert spec["op"] == "source"
    assert spec["kind"] == "rules_file"


def test_kind_is_used_when_no_source_kind():
    spec = normalize_event("generic", {"type": "source", "kind": "file", "uri": "src/main.py"})
    assert spec is not None
    assert spec["kind"] == "file"


def test_kind_only_payload_is_not_dropped():
    """A hook that sends only `kind` (no `type`) must still produce a Source op."""
    for kind in ("file", "web", "rules_file", "tool_output", "mcp_tool_desc", "human",
                 "user_prompt", "other"):
        spec = normalize_event("generic", {"kind": kind, "uri": "u"})
        assert spec is not None, kind
        assert spec["op"] == "source", kind
        assert spec["kind"] == kind, kind


def test_unknown_source_kind_defaults_to_web():
    spec = normalize_event("generic", {"type": "source", "source_kind": "not_a_kind", "uri": "u"})
    assert spec is not None
    assert spec["kind"] == "web"


def test_type_wins_over_kind_for_non_source_ops():
    mem = normalize_event("generic", {"type": "memory", "kind": "file", "text": "t"})
    assert mem is not None and mem["op"] == "memory"
    act = normalize_event("generic", {"type": "action", "kind": "file", "tool": "Bash"})
    assert act is not None and act["op"] == "action"


def test_kind_only_non_source_payloads_keep_their_op():
    read = normalize_event("generic", {"kind": "read", "node_id": "n1"})
    assert read is not None and read["op"] == "session_read"
    ses = normalize_event("generic", {"kind": "session", "session_id": "s"})
    assert ses is not None and ses["op"] == "session"


def test_unknown_events_are_ignored():
    assert normalize_event("generic", {"kind": "nonsense"}) is None
    assert normalize_event("generic", {"type": "nonsense"}) is None


def test_batch_inherits_session_id_and_keeps_order():
    specs = normalize_events("claude-code", {"session_id": "s1", "events": [
        {"type": "session"},
        {"kind": "web", "uri": "http://x"},
        {"type": "nonsense"},
        {"type": "memory", "text": "t"},
    ]})
    assert [s["op"] for s in specs] == ["session", "source", "memory"]
    assert all(s["session_id"] == "s1" for s in specs)


def test_empty_payload_produces_no_ops():
    assert normalize_events("generic", {"events": []}) == []
    assert normalize_events("generic", {}) == []
