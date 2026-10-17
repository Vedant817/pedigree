"""Tenant registry: hashed credentials resolved against live indexed authority."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from ..config import get_settings, graph_name, validate_tenant
from ..db.client import Db
from ..db.queries import (
    Q_REGISTRY_ALL,
    Q_REGISTRY_BY_DIGEST,
    Q_REGISTRY_BY_ID,
    Q_REGISTRY_ISSUE_OPERATOR,
    Q_REGISTRY_SET_STATUS,
    Q_REGISTRY_UPSERT,
)
from ..db.schema import ensure_schema
from ..errors import Conflict, InvalidArgument, NotFoundInGraph

RESERVED_TENANT_IDS = frozenset({"registry"})

REGISTRY_TENANT = "registry"


@dataclass(frozen=True)
class TenantCredential:
    tenant_id: str
    agent_token: str = field(repr=False)
    operator_token: str = field(repr=False)

    @property
    def token(self) -> str:
        """Compatibility alias; never returns operator authority."""
        return self.agent_token


@dataclass(frozen=True)
class TenantRecord:
    tenant_id: str
    status: str
    node_cap: int
    created_at: int


@dataclass(frozen=True)
class ResolvedPrincipal(TenantRecord):
    role: str


class TenantRegistry:
    def __init__(self, db: Db, settings=None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.gname = graph_name(REGISTRY_TENANT)
        ensure_schema(db, self.gname, label="Tenant")

    def has_tenants(self) -> bool:
        rows = self.db.ro_query(self.gname, Q_REGISTRY_ALL, {}, op="registry.list").result_set or []
        return len(rows) > 0

    def create_tenant(self, tenant_id: str, node_cap: int | None = None) -> TenantCredential:
        validate_tenant(tenant_id)
        if tenant_id in RESERVED_TENANT_IDS:
            raise InvalidArgument("reserved tenant id", detail={"id": tenant_id})
        if node_cap is not None and (not isinstance(node_cap, int) or node_cap < 1 or node_cap > 1_000_000):
            raise InvalidArgument("node_cap must be between 1 and 1000000",
                                  detail={"node_cap": node_cap})
        cap = node_cap if node_cap is not None else (self.settings.pedigree_node_cap)
        agent_token = f"ped_a_{tenant_id}_{secrets.token_urlsafe(32)}"
        operator_token = f"ped_o_{tenant_id}_{secrets.token_urlsafe(32)}"
        # ensure unique
        try:
            existing = self.get_record(tenant_id)
        except NotFoundInGraph:
            existing = None
        if existing is not None:
            raise Conflict("tenant exists", detail={"id": tenant_id})
        now = int(time.time() * 1000)
        self.db.query(
            self.gname,
            Q_REGISTRY_UPSERT,
            {"id": tenant_id, "cap": cap, "agent_sha": _sha(agent_token),
             "operator_sha": _sha(operator_token), "now": now},
            op="registry.create",
        )
        self.invalidate_cache()
        return TenantCredential(tenant_id, agent_token, operator_token)

    def issue_operator(self, tenant_id: str, *, rotate: bool = False) -> str:
        """Explicit deployment-admin recovery/rotation; old hashes are unrecoverable."""
        validate_tenant(tenant_id)
        record = self.get_record(tenant_id)
        if record.status != "active":
            raise Conflict("tenant is not active")
        token = f"ped_o_{tenant_id}_{secrets.token_urlsafe(32)}"
        rows = self.db.query(self.gname, Q_REGISTRY_ISSUE_OPERATOR,
                             {"id": tenant_id, "sha": _sha(token), "rotate": rotate},
                             op="registry.issue_operator").result_set or []
        if not rows:
            raise Conflict("operator credential already exists; explicit rotation required")
        self.invalidate_cache()
        return token

    def get_record(self, tenant_id: str) -> TenantRecord:
        res = self.db.ro_query(self.gname, Q_REGISTRY_BY_ID, {"id": tenant_id}, op="registry.get").result_set or []
        if not res:
            raise NotFoundInGraph("tenant not found", detail={"id": tenant_id})
        row = res[0]
        return TenantRecord(tenant_id=row[0], status=row[1], node_cap=int(row[2]), created_at=int(row[3]))

    def list_tenants(self) -> list[TenantRecord]:
        rows = self.db.ro_query(self.gname, Q_REGISTRY_ALL, {}, op="registry.list").result_set or []
        return [TenantRecord(tenant_id=r[0], status=r[1], node_cap=int(r[2]), created_at=int(r[3])) for r in rows]

    def revoke_tenant(self, tenant_id: str) -> None:
        try:
            self.get_record(tenant_id)
        except NotFoundInGraph:
            raise
        self.db.query(self.gname, Q_REGISTRY_SET_STATUS, {"id": tenant_id, "status": "revoked"},
                          op="registry.revoke")
        self.invalidate_cache()

    def resolve(self, token: str) -> ResolvedPrincipal | None:
        if not isinstance(token, str) or not token or token.strip() != token:
            return None
        digest = _sha(token)
        rows = self.db.ro_query(self.gname, Q_REGISTRY_BY_DIGEST, {"sha": digest},
                                op="registry.resolve").result_set or []
        # A digest matching multiple tenant candidates is corrupted/ambiguous
        # authority, even when only one candidate has a matching textual prefix.
        if len(rows) != 1:
            return None
        return self._principal(rows[0], token, digest)

    @staticmethod
    def _principal(row, token: str, digest: str) -> ResolvedPrincipal | None:
        if row[1] != "active":
            return None
        # Legacy slot is agent-only. A role prefix alone never grants authority.
        slots = ((row[5], "agent", "ped_a_"), (row[6], "operator", "ped_o_"),
                 (row[4], "agent", "ped_"))
        for stored, role, prefix in slots:
            if not isinstance(stored, str) or not hmac.compare_digest(stored, digest):
                continue
            if prefix == "ped_":
                # A genuine old tenant may itself begin a_/o_; compare its complete
                # expected prefix rather than interpreting those bytes as a role.
                valid_prefix = token.startswith(f"ped_{row[0]}_")
            else:
                valid_prefix = token.startswith(f"{prefix}{row[0]}_")
            if valid_prefix:
                return ResolvedPrincipal(row[0], row[1], int(row[2]), int(row[3]), role)
        return None

    def invalidate_cache(self) -> None:
        """Compatibility hook: every resolution already reads live authority."""


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
