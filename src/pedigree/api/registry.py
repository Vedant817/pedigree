"""Tenant registry stored in its own graph (`ped:registry`). Tokens are random and only a
sha256 is persisted, plus an in-process 30 s cache that is explicitly invalidated on changes."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from ..config import get_settings, graph_name, validate_id
from ..db.client import Db
from ..db.queries import Q_REGISTRY_ALL, Q_REGISTRY_BY_ID, Q_REGISTRY_SET_STATUS, Q_REGISTRY_UPSERT
from ..db.schema import ensure_schema
from ..errors import Conflict, NotFoundInGraph

REGISTRY_TENANT = "registry"
CACHE_TTL_S = 30.0


@dataclass(frozen=True)
class TenantCredential:
    tenant_id: str
    token: str


@dataclass(frozen=True)
class TenantRecord:
    tenant_id: str
    status: str
    node_cap: int
    created_at: int


class TenantRegistry:
    def __init__(self, db: Db, settings=None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.gname = graph_name(REGISTRY_TENANT)
        ensure_schema(db, self.gname)
        self._cache: dict[str, tuple[str, float]] = {}

    def has_tenants(self) -> bool:
        rows = self.db.ro_query(self.gname, Q_REGISTRY_ALL, {}, op="registry.list").result_set or []
        return len(rows) > 0

    def create_tenant(self, tenant_id: str, node_cap: int | None = None) -> TenantCredential:
        validate_id(tenant_id)
        cap = node_cap or self.settings.pedigree_node_cap
        token = f"ped_{tenant_id}_{secrets.token_urlsafe(32)}"
        digest = _sha(token)
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
            {"id": tenant_id, "cap": cap, "sha": digest, "now": now},
            op="registry.create",
        )
        self.invalidate_cache()
        return TenantCredential(tenant_id, token)

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

    def resolve(self, token: str) -> TenantRecord | None:
        digest = _sha(token)
        now = time.monotonic()
        cached = self._cache.get(token)
        if cached is not None and cached[1] > now:
            tid = cached[0]
            try:
                return self.get_record(tid)
            except NotFoundInGraph:
                self.invalidate_cache()
        for rec in self.list_tenants():
            if rec.status != "active":
                continue
            rows = self.db.ro_query(self.gname, Q_REGISTRY_BY_ID, {"id": rec.tenant_id},
                                     op="registry.resolve").result_set or []
            if not rows:
                continue
            stored = rows[0][4]
            if hmac.compare_digest(stored, digest):
                self._cache[token] = (rec.tenant_id, now + CACHE_TTL_S)
                return rec
        return None

    def invalidate_cache(self) -> None:
        self._cache.clear()


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
