"""Durable, resumable capture delivery. Metadata shares the tenant graph and quota.

Each step is restartable. Action creation stores its delivery fingerprint in the
same atomic query as its lineage, so a crash before advancing the cursor cannot
duplicate that action. The existing quota mutex serializes deliveries and writers.
"""
from __future__ import annotations

import hashlib
import json
import time

from ..config import Settings
from ..db import queries as Q
from ..db.client import Db
from ..errors import Conflict, InvalidArgument, NotFoundInGraph
from .gate import classify_action, load_policy
from .ingest import artifact_lookup, ensure_session, read_window, record_action, record_source
from .quota import QuotaPolicy, admission, enforce_quota


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def deliver(db: Db, gname: str, tenant: str, payload, specs: list[dict], settings: Settings, cap: int) -> dict:
    if not payload.session_id or not specs or specs[0]["op"] != "session" or any(spec["op"] not in {"source", "session", "session_read", "action"}
                                     or spec.get("session_id") != payload.session_id for spec in specs):
        raise InvalidArgument("delivery requires one session and capture events only")
    if any(s["op"] == "source" and not (s.get("uri") and s.get("content_hash")) for s in specs):
        raise InvalidArgument("replayable sources require uri and content_hash")
    digest = hashlib.sha256(_json(payload.model_dump()).encode()).hexdigest()
    rid = "capture_" + hashlib.sha256(payload.delivery_id.encode()).hexdigest()
    with admission(db, gname, QuotaPolicy(tenant, cap)) as locked:
        rows = locked.ro_query(gname, Q.Q_CAPTURE_GET, {"id": rid}, op="capture.receipt").result_set
        if rows:
            receipt = rows[0]
            if receipt[0] != digest:
                raise Conflict("delivery id already belongs to different events")
            cursor, aliases, created, plans, stamp = receipt[1], json.loads(receipt[2]), json.loads(receipt[3]), json.loads(receipt[4]), receipt[5]
        else:
            enforce_quota(locked, gname, 1)
            stamp, cursor, aliases, created, plans = int(time.time() * 1000), 0, {}, [], {}
            locked.query(gname, Q.Q_CAPTURE_CREATE,
                         {"id": rid, "digest": digest, "tenant": tenant, "now": stamp}, op="capture.begin")

        def save(next_cursor):
            locked.query(gname, Q.Q_CAPTURE_ADVANCE,
                         {"id": rid, "cursor": next_cursor, "aliases": _json(aliases),
                          "created": _json(created), "plans": _json(plans)}, op="capture.progress")

        def resolve(value):
            return aliases.get(value, value)

        for index in range(cursor, len(specs)):
            spec = specs[index]
            op, sid = spec["op"], spec["session_id"]
            key = digest + ":" + str(index)
            nid = "cap_" + hashlib.sha256((rid + ":" + str(index)).encode()).hexdigest()[:40]
            time_key = "at:" + str(index)
            if time_key not in plans:
                plans[time_key] = int(time.time() * 1000)
                save(index)
            observed_at = plans[time_key]
            if op == "session":
                ensure_session(locked, gname, tenant, sid, runtime=payload.runtime, now=observed_at)
            elif op == "source":
                plan_key = str(index)
                if plan_key not in plans:
                    existing = artifact_lookup(locked, gname, spec["artifact_key"]) if spec.get("artifact_key") else None
                    # Persist lookup choice BEFORE a later event can change the artifact head.
                    plans[plan_key] = existing[1] if existing else ""
                    save(index)
                if plans[plan_key]:
                    canonical = plans[plan_key]
                else:
                    result = record_source(locked, gname, tenant, kind=spec["kind"], uri=spec["uri"],
                                           content_hash=spec["content_hash"], title=spec.get("title"),
                                           integrity="untrusted", conf=spec.get("conf"), id=nid, now=observed_at)
                    canonical = result.id
                if spec.get("id"):
                    aliases[spec["id"]] = canonical
                created.append(canonical)
            elif op == "session_read":
                result = locked.query(gname, Q.Q_CAPTURE_READ,
                                      {"sess": sid, "n": resolve(spec["node_id"]), "now": observed_at}, op="capture.read")
                if not result.result_set:
                    raise NotFoundInGraph("session or node not found")
            elif op == "action":
                existing = locked.ro_query(gname, Q.Q_CAPTURE_ACTION, {"id": nid}, op="capture.action").result_set
                if existing:
                    if existing[0][0] != key:
                        raise Conflict("capture action identity conflict")
                else:
                    parents = [resolve(value) for value in spec.get("relied_on") or []] or read_window(
                        locked, gname, sid, settings.pedigree_read_window)
                    effect, risk = classify_action(load_policy(settings.pedigree_policy_file), spec["tool"],
                                                   spec["summary"], effect=spec.get("effect"), risk=spec.get("risk"))
                    record_action(locked, gname, tenant, id=nid, tool=spec["tool"], summary=spec["summary"],
                                  relied_on=parents, effect=effect, risk=risk, artifacts=spec.get("artifacts") or [],
                                  artifact_key=spec.get("artifact_key"), decision=spec.get("decision"),
                                  via="hook" if payload.runtime in {"claude-code", "opencode"} else "agent_reported",
                                  now=observed_at, capture_key=key, session_id=sid, defer_session_read=True)
                # Creation and session-edge repair are independently replayable.
                repaired = locked.query(gname, Q.Q_CAPTURE_READ, {"sess": sid, "n": nid, "now": observed_at}, op="capture.read")
                if not repaired.result_set:
                    raise NotFoundInGraph("capture session not found")
                created.append(nid)
                if spec.get("id"):
                    aliases[spec["id"]] = nid
            save(index + 1)
        return {"created": created, "delivery_id": payload.delivery_id}
