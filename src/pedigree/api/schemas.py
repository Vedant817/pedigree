"""Shared API request/response models. Every body is strict: `tenant` in any payload is
rejected by `extra="forbid", so identity can only come from the bearer token (F-05 ADR)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- ingest payloads ---------------------------------------------------------

class SourceCreate(StrictModel):
    kind: str = Field(min_length=1, max_length=32)
    uri: str | None = None
    title: str | None = None
    content_hash: str | None = None
    integrity: Literal["trusted", "untrusted"] | None = None
    conf: list[str] | None = None
    id: str | None = None


class MemoryCreate(StrictModel):
    text: str = ""
    mkind: str = "fact"
    derived_from: list[str] = Field(default_factory=list)
    corroborated_by: list[str] = Field(default_factory=list)
    artifact: str | None = None
    artifact_key: str | None = None
    content_hash: str | None = None
    conf: list[str] | None = None
    agent_id: str | None = None
    session_id: str | None = None
    id: str | None = None
    via: str = "cite"


class ActionCreate(StrictModel):
    tool: str = Field(min_length=1, max_length=128)
    summary: str = ""
    relied_on: list[str] = Field(default_factory=list)
    decision: str | None = None
    effect: Literal["reversible", "irreversible", "unknown"] | None = None
    risk: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    artifact_key: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    id: str | None = None
    via: str = "cite"


class CorroborateRequest(StrictModel):
    memory_id: str
    source_id: str
    by: Literal["agent", "human", "scanner"] = "agent"


class RevokeRequest(StrictModel):
    root_id: str
    reason: str = ""
    dry_run: bool = False
    kind: Literal["revoke", "supersede"] = "revoke"


class ReinstateRequest(StrictModel):
    root_id: str
    dry_run: bool = False


class SessionReadRequest(StrictModel):
    session_id: str
    node_id: str
    ensure: Literal["yes", "no"] = "yes"
    runtime: str = "other"


class EnsureSessionRequest(StrictModel):
    session_id: str
    runtime: str = "other"
    agent_id: str | None = None


class TenantCreate(StrictModel):
    id: str
    node_cap: int | None = None


class EventResponse(BaseModel):
    id: str
    status: str
    low_integrity: bool
    conf_eff: list[str]
    warnings: list[str] = Field(default_factory=list)


class OkResponse(BaseModel):
    detail: Any = None


class EventsPayload(StrictModel):
    runtime: str = Field(default="generic", max_length=64)
    session_id: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class GateAction(StrictModel):
    tool: str = Field(min_length=1, max_length=128)
    summary: str = Field(default="", max_length=300)
    effect: Literal["reversible", "irreversible", "unknown"] | None = None
    risk: Literal["low", "medium", "high"] | None = None
    audience: list[str] | None = Field(default=None, max_length=8)


class GateRequest(StrictModel):
    action: GateAction
    relied_on: list[str] = Field(default_factory=list, max_length=64)
    session_id: str | None = Field(default=None, max_length=128)
    max_depth: int = Field(default=12, ge=1, le=12)
    record: bool = False
