"""Shared strict public-input contracts, independent of HTTP and the graph engine."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    create_model,
)

from .config import ID_RE, LIMITS, SOURCE_KINDS, TENANT_RE
from .errors import InvalidArgument


def _single_line(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("control characters are forbidden")
    return value


def _prose(value: str) -> str:
    if any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in value):
        raise ValueError("control characters are forbidden")
    return value


def _line(maximum: int, minimum: int = 0):
    return Annotated[str, StringConstraints(strict=True, min_length=minimum, max_length=maximum), AfterValidator(_single_line)]


Id = Annotated[str, StringConstraints(strict=True, pattern=ID_RE.pattern, max_length=LIMITS["id_len"])]
TenantId = Annotated[str, StringConstraints(strict=True, pattern=TENANT_RE.pattern)]
Uri = _line(LIMITS["uri_len"])
Title = _line(LIMITS["title_len"])
Artifact = _line(LIMITS["artifact_str_len"], 1)
ArtifactKey = _line(LIMITS["artifact_str_len"] * 2, 1)
Tool = _line(128, 1)
Token = _line(512)
Runtime = _line(64, 1)
ConfTag = _line(32, 1)
ProseText = Annotated[str, StringConstraints(strict=True, max_length=LIMITS["text_len"]), AfterValidator(_prose)]
Summary = Annotated[str, StringConstraints(strict=True, max_length=LIMITS["summary_len"]), AfterValidator(_prose)]
Reason = Annotated[str, StringConstraints(strict=True, max_length=LIMITS["reason_len"]), AfterValidator(_prose)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9A-Fa-f]{64}$", min_length=64, max_length=64)]
Conf = Annotated[list[ConfTag], Field(strict=True, max_length=LIMITS["conf_tags"])]
DependencyIds = Annotated[list[Id], Field(strict=True, max_length=LIMITS["derived_from"])]
CorroboratorIds = Annotated[list[Id], Field(strict=True, max_length=LIMITS["corroborated_by"])]
ArtifactList = Annotated[list[Artifact], Field(strict=True, max_length=LIMITS["artifacts"])]
Audience = Annotated[list[ConfTag], Field(strict=True, max_length=8)]
SourceKind = Literal["user_prompt", "file", "web", "tool_output", "rules_file", "mcp_tool_desc", "human", "other", "scanner"]
MemoryKind = Literal["fact", "summary", "decision", "preference", "procedure", "rule"]
Effect = Literal["reversible", "irreversible", "unknown"]
Risk = Literal["low", "medium", "high"]
Integrity = Literal["trusted", "untrusted"]
Via = Literal["cite", "session_read", "agent_reported", "hook"]
By = Literal["agent", "human", "scanner"]
Depth = Annotated[int, Field(strict=True, ge=1, le=LIMITS["depth_max"])]
Roots = Annotated[list[Id], Field(strict=True, min_length=1, max_length=LIMITS["whatif_roots"])]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class SourceFields(StrictModel):
    kind: SourceKind = "web"
    uri: Uri | None = None
    title: Title | None = None
    content_hash: Hash | None = None
    integrity: Integrity | None = None
    conf: Conf | None = None
    id: Id | None = None


class MemoryFields(StrictModel):
    text: ProseText = ""
    mkind: MemoryKind = "fact"
    derived_from: DependencyIds = Field(default_factory=list)
    corroborated_by: CorroboratorIds = Field(default_factory=list)
    artifact: Artifact | None = None
    artifact_key: ArtifactKey | None = None
    content_hash: Hash | None = None
    conf: Conf | None = None
    agent_id: Id | None = None
    session_id: Id | None = None
    id: Id | None = None
    via: Via = "cite"


class ActionFields(StrictModel):
    tool: Tool
    summary: Summary = ""
    relied_on: DependencyIds = Field(default_factory=list)
    decision: _line(32) | None = None
    effect: Effect | None = None
    risk: Risk | None = None
    artifacts: ArtifactList = Field(default_factory=list)
    artifact_key: ArtifactKey | None = None
    session_id: Id | None = None
    agent_id: Id | None = None
    id: Id | None = None
    via: Via = "cite"


class SourceEvent(SourceFields):
    artifact_key: ArtifactKey | None = None
    # Scanner is a privileged claim recognized by authentication, but it is not
    # a supported engine Source kind. Events authorize first, then reject it
    # here before any earlier valid event can be persisted.
    kind: Literal["user_prompt", "file", "web", "tool_output", "rules_file", "mcp_tool_desc", "human", "other"] = "web"
    op: Literal["source"] = "source"
    session_id: Id | None = None


class MemoryEvent(StrictModel):
    op: Literal["memory"] = "memory"
    text: ProseText = ""
    derived_from: DependencyIds | None = None
    corroborated_by: CorroboratorIds | None = None
    artifact: Artifact | None = None
    artifact_key: ArtifactKey | None = None
    id: Id | None = None
    session_id: Id | None = None


class ActionEvent(StrictModel):
    op: Literal["action"] = "action"
    tool: Tool = "unknown"
    summary: Summary = ""
    relied_on: DependencyIds | None = None
    decision: _line(32) | None = None
    effect: Effect | None = None
    risk: Risk | None = None
    artifacts: ArtifactList | None = None
    artifact_key: ArtifactKey | None = None
    id: Id | None = None
    session_id: Id | None = None


class SessionEvent(StrictModel):
    op: Literal["session"] = "session"
    session_id: Id


class ReadEvent(StrictModel):
    op: Literal["session_read"] = "session_read"
    session_id: Id
    node_id: Id


_OPERATIONS = {
    **dict.fromkeys(("source", "source_read", "source.create"), "source"),
    **dict.fromkeys(("memory", "memory_created", "remember"), "memory"),
    **dict.fromkeys(("action", "action_executed", "tool_use", "tool_executed"), "action"),
    **dict.fromkeys(("session", "session_start", "ensure_session"), "session"),
    **dict.fromkeys(("session_read", "read"), "session_read"),
}
_EVENT_MODELS = {"source": SourceEvent, "memory": MemoryEvent, "action": ActionEvent,
                 "session": SessionEvent, "session_read": ReadEvent}
_RAW_FIELDS = {
    "source": {"type", "kind", "source_kind", "uri", "title", "id", "integrity", "content_hash", "conf", "session_id", "artifact_key"},
    "memory": {"type", "kind", "text", "derived_from", "corroborated_by", "artifact", "artifact_key", "id", "session_id"},
    "action": {"type", "kind", "tool", "tool_name", "summary", "title", "relied_on", "memories", "decision", "effect", "risk", "artifacts", "artifact_key", "id", "session_id"},
    "session": {"type", "kind", "session_id"},
    "session_read": {"type", "kind", "session_id", "node_id"},
}


def _alias(raw: dict, canonical: str, alias: str, default):
    if canonical in raw and alias in raw and raw[canonical] != raw[alias]:
        raise InvalidArgument("invalid event arguments")
    return raw[canonical] if canonical in raw else raw.get(alias, default)


def validate_event(raw: dict[str, Any], *, session_id: str | None = None) -> dict:
    """Validate every accepted raw field before aliases can discard caller input."""
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise InvalidArgument("invalid event arguments")
    discriminator = raw.get("type", raw.get("kind"))
    if not isinstance(discriminator, str):
        raise InvalidArgument("invalid event arguments")
    discriminator = discriminator.lower()
    operation = _OPERATIONS.get(discriminator)
    if operation is None and "type" not in raw and discriminator in SOURCE_KINDS:
        operation = "source"
    if operation is None or set(raw) - _RAW_FIELDS[operation]:
        raise InvalidArgument("invalid event arguments")
    if operation != "source" and "type" in raw and "kind" in raw:
        if not isinstance(raw["kind"], str) or _OPERATIONS.get(raw["kind"].lower()) != operation:
            raise InvalidArgument("invalid event arguments")
    values = {key: value for key, value in raw.items() if key not in ("type", "kind")}
    values.setdefault("session_id", session_id)
    values["op"] = operation
    if operation == "source":
        raw_kind = raw.get("kind")
        if "kind" in raw and not isinstance(raw_kind, str):
            raise InvalidArgument("invalid event arguments")
        # `kind` doubles as the discriminator in legacy hook events. An
        # operation alias is not a competing source classification.
        classified_kind = raw_kind if raw_kind in (*SOURCE_KINDS, "scanner") else None
        if raw_kind is not None and classified_kind is None:
            if _OPERATIONS.get(raw_kind.lower()) != "source":
                raise InvalidArgument("invalid event arguments")
        if "source_kind" in raw and classified_kind is not None and raw["source_kind"] != classified_kind:
            raise InvalidArgument("invalid event arguments")
        values["kind"] = raw.get("source_kind", classified_kind or "web")
        values.pop("source_kind", None)
    elif operation == "action":
        values["tool"] = _alias(raw, "tool", "tool_name", "unknown")
        values["summary"] = _alias(raw, "summary", "title", "")
        values["relied_on"] = _alias(raw, "relied_on", "memories", None)
        for key in ("tool_name", "title", "memories"):
            values.pop(key, None)
    try:
        return _EVENT_MODELS[operation].model_validate(values).model_dump()
    except ValidationError:
        raise InvalidArgument("invalid event arguments") from None


# MCP schemas mirror exposed tool parameters; omitted values stay omitted so the
# registered function remains the single source of its behavioral defaults.
_AUTH = {"tenant_id": (TenantId | None, None), "token": (Token | None, None)}
_TOKEN = {"token": (Token | None, None)}


def _model(name: str, fields: dict):
    return create_model(name, __base__=StrictModel, **fields)


def _selected(model, names):
    return {name: (model.model_fields[name].annotation,
                   model.model_fields[name].get_default(call_default_factory=True)) for name in names}


_TOOL_MODELS = {
    "pedigree_health": _model("HealthArguments", {}),
    "pedigree_record_source": _model("SourceArguments", {**_AUTH, **_selected(SourceFields, ("kind", "uri", "title", "id", "conf", "integrity"))}),
    "pedigree_remember": _model("MemoryArguments", {**_AUTH, "text": (ProseText, ""), "mkind": (MemoryKind, "fact"),
        "derived_from": (DependencyIds | None, None), "corroborated_by": (CorroboratorIds | None, None),
        "artifact": (Artifact | None, None), "artifact_key": (ArtifactKey | None, None), "id": (Id | None, None)}),
    "pedigree_record_action": _model("ActionArguments", {**_AUTH, "tool": (Tool, ...), "summary": (Summary, ""),
        "relied_on": (DependencyIds | None, None), "decision": (_line(32) | None, None), "effect": (Effect | None, None),
        "risk": (Risk | None, None), "artifacts": (ArtifactList | None, None), "id": (Id | None, None)}),
    "pedigree_corroborate": _model("CorroborateArguments", {**_AUTH, "memory_id": (Id, ...), "source_id": (Id, ...), "by": (By, "agent")}),
    "pedigree_check_action": _model("GateArguments", {**_TOKEN, "tool": (Tool, ...), "summary": (Summary, ""),
        "relied_on": (DependencyIds | None, None), "session_id": (Id | None, None), "effect": (Effect | None, None),
        "risk": (Risk | None, None), "audience": (Audience | None, None), "max_depth": (Depth, 12), "record": (bool, False)}),
    "pedigree_revoke": _model("RevokeArguments", {**_AUTH, "root_id": (Id, ...), "reason": (Reason, ""), "dry_run": (bool, False), "kind": (Literal["revoke", "supersede"], "revoke")}),
    "pedigree_reinstate": _model("ReinstateArguments", {**_AUTH, "root_id": (Id, ...), "dry_run": (bool, False)}),
    "pedigree_blame": _model("BlameArguments", {**_AUTH, "node_id": (Id, ...), "max_depth": (Depth, 12)}),
    "pedigree_impact": _model("ImpactArguments", {**_AUTH, "node_id": (Id, ...), "max_depth": (Depth, 12)}),
    "pedigree_whatif": _model("WhatifArguments", {**_AUTH, "roots": (Roots, ...)}),
    "pedigree_audit_sources": _model("AuditArguments", {**_AUTH, "limit": (Annotated[int, Field(strict=True, ge=1, le=LIMITS["audit_limit"])], 50)}),
    "pedigree_report": _model("ReportArguments", _AUTH),
}


def validate_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict) or name not in _TOOL_MODELS:
        raise InvalidArgument("invalid tool arguments")
    try:
        return _TOOL_MODELS[name].model_validate(arguments).model_dump(exclude_unset=True)
    except ValidationError:
        raise InvalidArgument("invalid tool arguments") from None
