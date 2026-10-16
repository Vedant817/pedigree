"""Request-wide quota admission under a non-expiring, owner-token Redis mutex.

Requires a stable primary and coordination keys protected from eviction/loss. A crash
or ambiguous mutation strands the lock; recover only with all writers stopped and
DB work quiescent. This is intentionally not a lease or a failover protocol.
"""

from __future__ import annotations

import functools
import inspect
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from ..config import graph_name
from ..db import queries as Q
from ..db.schema import node_count
from ..errors import Conflict, InvalidArgument, QuotaExceeded, Unavailable

_RELEASE = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


@dataclass(frozen=True)
class QuotaPolicy:
    tenant: str
    node_cap: int
    acquire_seconds: float = 2.0

    def __post_init__(self):
        if self.node_cap < 1 or self.acquire_seconds < 0:
            raise InvalidArgument("invalid quota policy")


def lock_key(gname):
    return "pedigree:quota:mutex:" + gname


class _GuardedDb:
    def __init__(self, db, policy, gname, token):
        self.db, self.policy, self.gname = db, policy, gname
        self.token = token
        self.uncertain = False

    def __getattr__(self, name):
        return getattr(self.db, name)

    def query(self, *args, **kwargs):
        try:
            owner = self.db.client.connection.get(lock_key(self.gname))
            if isinstance(owner, bytes):
                owner = owner.decode("ascii")
            if owner != self.token:
                raise Unavailable("quota mutex ownership lost")
            return self.db.query(*args, **kwargs)
        except Conflict:
            # A definite constraint rejection cannot still be executing.
            raise
        except Exception:
            # Even a mapped timeout/connection failure may have executed a write.
            self.uncertain = True
            raise


_current = ContextVar("pedigree_quota_admission", default=None)


@contextmanager
def admission(db, gname, policy):
    current = _current.get()
    if policy is None:
        if current is not None:
            if current.gname != gname:
                raise InvalidArgument("quota admission graph mismatch")
            yield current
        else:
            yield db
        return
    if gname != graph_name(policy.tenant):
        raise InvalidArgument("quota policy graph mismatch")
    if current is not None:
        if current.gname != gname or current.policy != policy:
            raise InvalidArgument("quota admission policy mismatch")
        yield current
        return
    token = secrets.token_hex(32)
    key = lock_key(gname)
    connection = db.client.connection
    deadline = time.monotonic() + policy.acquire_seconds
    while True:
        try:
            acquired = connection.set(key, token, nx=True)
        except Exception as exc:
            raise Unavailable("quota coordination unavailable") from exc
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise Unavailable("tenant writer busy; operator recovery may be required")
        time.sleep(min(0.025, max(0, deadline - time.monotonic())))
    guarded = _GuardedDb(db, policy, gname, token)
    context = _current.set(guarded)
    try:
        yield guarded
    finally:
        _current.reset(context)
        if not guarded.uncertain:
            try:
                released = connection.eval(_RELEASE, 1, key, token)
                if released != 1:
                    raise Unavailable("quota mutex ownership lost")
            except Unavailable:
                raise
            except Exception as exc:
                raise Unavailable("quota mutex release unavailable") from exc


def enforce_quota(db, gname, add=1):
    current = _current.get()
    if current is None:
        return  # trusted, standalone engine calls have no registry dependency
    if current.gname != gname:
        raise InvalidArgument("quota admission graph mismatch")
    used = node_count(db, gname)
    if add > 0 and used + add > current.policy.node_cap:
        raise QuotaExceeded(
            "node cap exceeded", detail={"nodes": used, "cap": current.policy.node_cap, "add": add}
        )


def _source_key(db, gname, tenant, spec):
    from .ingest import derived_source_id

    uri, digest, explicit = spec.get("uri"), spec.get("content_hash"), spec.get("id")
    if uri and digest:
        digest = digest.lower()
        rows = (
            db.ro_query(
                gname, Q.Q_SOURCE_BY_ARTIFACT, {"tenant": tenant, "uri": uri, "hash": digest}
            ).result_set
            or []
        )
        return ("artifact", tenant, uri, digest), bool(rows), (rows[0][0] if rows else explicit)
    if uri and not explicit:
        nid = derived_source_id(tenant, uri)
        rows = db.ro_query(gname, Q.Q_NODE_BY_ID, {"id": nid}).result_set or []
        return ("id", nid), bool(rows), nid
    # Explicit CREATE retains its existing conflict behavior (not retry-idempotent).
    return (("id", explicit) if explicit else ("generated", object())), False, explicit


def preflight(db, gname, tenant, specs):
    """Count exact prospective new identities, including repeated in-batch sources/sessions.

    Call only while holding admission; quota rejection happens before any batch mutation.
    Subsequent input or DB errors retain existing sequential partial-write semantics.
    """
    additions = set()
    claimed_ids = set()

    def claim(node_id):
        if not node_id:
            return
        if node_id in claimed_ids or db.ro_query(gname, Q.Q_NODE_BY_ID, {"id": node_id}).result_set:
            raise Conflict("node id already exists", detail={"id": node_id})
        claimed_ids.add(node_id)

    for spec in specs:
        op = spec.get("op")
        if op == "source":
            key, exists, node_id = _source_key(db, gname, tenant, spec)
            if not exists and key not in additions:
                claim(node_id)
                additions.add(key)
        elif op == "session":
            sid = spec.get("session_id")
            rows = db.ro_query(gname, Q.Q_GET_SESSION, {"id": sid}).result_set or []
            if not rows and ("id", sid) not in additions:
                claim(sid)
                additions.add(("id", sid))
        elif op in ("memory", "action"):
            claim(spec.get("id"))
            additions.add(("id", spec["id"]) if spec.get("id") else ("generated", object()))
    enforce_quota(db, gname, len(additions))
    return len(additions)


def quota_write(op):
    """Optional explicit policy; nested operations reuse the enclosing request admission."""

    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(db, gname, *args, quota=None, **kwargs):
            with admission(db, gname, quota) as guarded:
                bound = signature.bind(guarded, gname, *args, **kwargs)
                values = bound.arguments
                tenant = values.get("tenant")
                current = _current.get()
                effective_policy = quota if quota is not None else (current.policy if current else None)
                if effective_policy is not None and tenant is not None and tenant != effective_policy.tenant:
                    raise InvalidArgument("quota policy tenant mismatch")
                if _current.get() is not None:
                    if op in ("source", "session", "memory", "action"):
                        spec = dict(values)
                        spec["op"] = op
                        preflight(guarded, gname, tenant, [spec])
                    elif op in ("revoke", "reinstate") and not values.get("dry_run", False):
                        rows = (
                            guarded.ro_query(gname, Q.Q_NODE_BY_ID, {"id": values["root_id"]}).result_set
                            or []
                        )
                        if rows and (
                            (rows[0][2] == "revoked") if op == "reinstate" else (rows[0][2] != "revoked")
                        ):
                            # Both CAS operations create one Revocation ledger node.
                            enforce_quota(guarded, gname, 1)
                return fn(guarded, gname, *args, **kwargs)

        return wrapped

    return decorate
