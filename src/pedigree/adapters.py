"""Strict event normalization shared by capture adapters and REST ingestion."""
from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from .config import SOURCE_KINDS
from .errors import InvalidArgument
from .validation import Id, Runtime, validate_event

SUPPORTED_RUNTIME = {"claude-code", "opencode", "generic"}
SOURCE_KIND_ALIASES = frozenset(SOURCE_KINDS)


def normalize_event(runtime: str, event: dict[str, Any]) -> dict[str, Any]:
    # Unknown runtime names deliberately use generic semantics. Event shape and
    # fields must still pass the same contract before any information is dropped.
    return validate_event(event)


def normalize_events(runtime: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise InvalidArgument("invalid event arguments")
    try:
        TypeAdapter(Runtime).validate_python(runtime)
        sid = TypeAdapter(Id | None).validate_python(payload.get("session_id"))
    except ValidationError:
        raise InvalidArgument("invalid event arguments") from None
    if "events" not in payload:
        if not payload:
            return []
        return [validate_event(payload, session_id=sid)]
    events = payload["events"]
    if not isinstance(events, list):
        raise InvalidArgument("invalid event arguments")
    return [validate_event(raw, session_id=sid) for raw in events]
