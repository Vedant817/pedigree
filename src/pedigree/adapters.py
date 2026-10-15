"""Generic event normalization for hook/tool payloads (F-07).

The endpoint is the choke point: runtimes send opaque-ish evidence of what actually
happened, and we translate only fields we understand into engine operations.
"""

from __future__ import annotations

from typing import Any

from .config import SOURCE_KINDS

SUPPORTED_RUNTIME = {"claude-code", "opencode", "generic"}

#: Event `kind` values that identify a Source without an explicit `type` (kind-only payloads
#: from hooks would otherwise be dropped entirely - audit finding, docs/qa/F-07.md).
SOURCE_KIND_ALIASES = frozenset(SOURCE_KINDS)


def _source_kind(event: dict[str, Any]) -> str:
    """`source_kind` first, then `kind` when it is a real source kind; `web` last (docs/01 §7.3)."""
    raw = event.get("source_kind") or event.get("kind")
    return raw if raw in SOURCE_KINDS else "web"


def normalize_event(runtime: str, event: dict[str, Any]) -> dict[str, Any] | None:
    if runtime not in SUPPORTED_RUNTIME:
        runtime = "generic"
    kind = (event.get("type") or event.get("kind") or "").lower()
    base = {"session_id": event.get("session_id")}
    if kind in ("source_read", "source", "source.create") or (
        kind in SOURCE_KIND_ALIASES and "type" not in event
    ):
        # The caller id names the node at creation; identity itself is derived from
        # (uri, content_hash) in the engine (ADR-008), so the same artifact always
        # converges on one node whatever id this capture used.
        spec = {
            "op": "source",
            "kind": _source_kind(event),
            "uri": event.get("uri"),
            "title": event.get("title"),
            "id": event.get("id"),
            "integrity": event.get("integrity"),
            "content_hash": event.get("content_hash"),
            "conf": event.get("conf"),
        }
    elif kind in ("memory", "memory_created", "remember"):
        spec = {
            "op": "memory",
            "text": event.get("text", ""),
            "derived_from": event.get("derived_from") or [],
            "corroborated_by": event.get("corroborated_by") or [],
            "artifact": event.get("artifact"),
            "artifact_key": event.get("artifact_key"),
            "id": event.get("id"),
        }
    elif kind in ("action", "action_executed", "tool_use", "tool_executed"):
        spec = {
            "op": "action",
            "tool": event.get("tool") or event.get("tool_name") or "unknown",
            "summary": event.get("summary") or event.get("title") or "",
            "relied_on": event.get("relied_on") or event.get("memories") or [],
            "decision": event.get("decision"),
            "effect": event.get("effect"),
            "risk": event.get("risk"),
            "artifacts": event.get("artifacts") or [],
            "artifact_key": event.get("artifact_key"),
            "id": event.get("id"),
            "session_id": event.get("session_id"),
        }
    elif kind in ("session", "session_start", "ensure_session"):
        spec = {"op": "session"}
    elif kind in ("session_read", "read"):
        spec = {"op": "session_read", "session_id": event.get("session_id"), "node_id": event.get("node_id")}
    else:
        return None
    spec.update(base)
    return spec


def normalize_events(runtime: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("events")
    if events is None:
        events = [payload]
    out = []
    for raw in events:
        raw = dict(raw or {})
        raw.setdefault("session_id", payload.get("session_id"))
        spec = normalize_event(runtime, raw)
        if spec is not None:
            out.append(spec)
    return out
