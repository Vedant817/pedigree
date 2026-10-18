"""Shared API request/response models. Every body is strict: `tenant` in any payload is
rejected by `extra="forbid", so identity can only come from the bearer token (F-05 ADR)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ..validation import (
    ActionFields,
    Audience,
    By,
    DependencyIds,
    Depth,
    Effect,
    Id,
    MemoryFields,
    Reason,
    Risk,
    Roots,
    Runtime,
    SourceFields,
    SourceKind,
    StrictModel,
    Summary,
    TenantId,
    Tool,
)


class SourceCreate(SourceFields):
    kind: SourceKind


class MemoryCreate(MemoryFields):
    pass


class ActionCreate(ActionFields):
    pass


class CorroborateRequest(StrictModel):
    """`human`/`scanner` require the tenant operator bearer; agents assert `agent`."""

    memory_id: Id
    source_id: Id
    by: By = "agent"


class WhatIfRequest(StrictModel):
    roots: Roots
    reason: Reason = "what-if"


class RevokeRequest(StrictModel):
    root_id: Id
    reason: Reason = ""
    dry_run: bool = False
    kind: Literal["revoke", "supersede"] = "revoke"


class ReinstateRequest(StrictModel):
    root_id: Id
    dry_run: bool = False


class SessionReadRequest(StrictModel):
    session_id: Id
    node_id: Id
    ensure: Literal["yes", "no"] = "yes"
    runtime: Runtime = "other"


class EnsureSessionRequest(StrictModel):
    session_id: Id
    runtime: Runtime = "other"
    agent_id: Id | None = None


class TenantCreate(StrictModel):
    id: TenantId
    node_cap: Annotated[int, Field(strict=True, ge=1, le=1_000_000)] | None = None


class ResumeRequest(StrictModel):
    tenant: TenantId


class EventResponse(BaseModel):
    id: str
    status: str
    low_integrity: bool
    conf_eff: list[str]
    warnings: list[str] = Field(default_factory=list)


class OkResponse(BaseModel):
    detail: Any = None


class EventsPayload(StrictModel):
    runtime: Runtime = "generic"
    delivery_id: Id | None = None
    session_id: Id | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class GateAction(StrictModel):
    tool: Tool
    summary: Summary = ""
    effect: Effect | None = None
    risk: Risk | None = None
    audience: Audience | None = None


class GateRequest(StrictModel):
    action: GateAction
    relied_on: DependencyIds = Field(default_factory=list)
    session_id: Id | None = None
    max_depth: Depth = 12
    record: bool = False
