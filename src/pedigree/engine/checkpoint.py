"""Offline, journaled tenant recovery. All writers MUST be stopped by the operator.

Redis AOF fsync precedes each next step; immutable snapshots remain until explicit
drop. A pending journal is never automatically expired or discarded on an error.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time

from ..config import checkpoint_graph_name, graph_name, validate_tenant
from ..db import queries as Q
from ..db.client import DB_EXC
from ..db.schema import check_invariants
from ..errors import Conflict, InvalidArgument, NotFoundInGraph, Unavailable
from .quota import lock_key

MAX_CHECKPOINTS = 20
MAX_NODES = 200_000
MAX_EDGES = 1_000_000
_UNLOCK = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"


class Checkpoints:
    def __init__(self, db, tenant: str):
        self.db = db
        self.tenant = validate_tenant(tenant)
        if tenant == "registry":
            raise InvalidArgument("reserved tenant id")
        self.main = graph_name(tenant)
        self.connection = db.client.connection
        self.key = "pedigree:recovery:" + tenant
        self.index = "pedigree:checkpoints:" + tenant

    def _durable(self, *command):
        # Nontransactional pipeline pins both commands to ONE Redis connection.
        # WAITAOF applies to that connection's preceding write offset.
        try:
            with self.connection.pipeline(transaction=False) as pipe:
                pipe.execute_command(*command)
                pipe.execute_command("WAITAOF", 1, 0, 5000)
                result, persisted = pipe.execute()
        except DB_EXC as exc:
            raise Unavailable("recovery database command failed; keep writers stopped") from exc
        if persisted[0] != 1:
            raise Unavailable("recovery persistence not confirmed; keep writers stopped")
        return result

    def _ready(self):
        # v4.22.1 replay can append schema effects for historical graphs that
        # were later deleted, poisoning a subsequent restart. Under the global
        # stopped-writer boundary, start from a compact current-state AOF base.
        # Never overlap this fork with GRAPH.COPY and never proceed on timeout.
        deadline = time.monotonic() + 60
        try:
            info = self.connection.info("persistence")
            if not info.get("aof_enabled"):
                raise Unavailable("offline recovery requires AOF persistence")
            while info.get("aof_rewrite_in_progress") or info.get("aof_rewrite_scheduled"):
                if time.monotonic() >= deadline:
                    raise Unavailable("AOF compaction timed out; keep writers stopped")
                time.sleep(0.05)
                info = self.connection.info("persistence")
            generation = info["aof_rewrites"]
            self.connection.bgrewriteaof()
            while True:
                info = self.connection.info("persistence")
                if info["aof_rewrites"] > generation and not (
                    info.get("aof_rewrite_in_progress") or info.get("aof_rewrite_scheduled")
                ):
                    if info.get("aof_last_bgrewrite_status") != "ok":
                        raise Unavailable("AOF compaction failed; keep writers stopped")
                    return
                if time.monotonic() >= deadline:
                    raise Unavailable("AOF compaction timed out; keep writers stopped")
                time.sleep(0.05)
        except DB_EXC as exc:
            raise Unavailable("AOF compaction unavailable; keep writers stopped") from exc

    def _exists(self, graph):
        return bool(self.connection.exists(graph))

    def _fingerprint(self, graph):
        if not self._exists(graph):
            raise NotFoundInGraph("graph not in the database")
        counts = self.db.ro_query(graph, Q.Q_CHECKPOINT_COUNTS, op="checkpoint.counts").result_set[0]
        if counts[0] > MAX_NODES or counts[1] > MAX_EDGES:
            raise InvalidArgument("graph exceeds offline recovery verification limits")
        nodes = self.db.ro_query(graph, Q.Q_CHECKPOINT_NODES, op="checkpoint.nodes").result_set
        edges = self.db.ro_query(graph, Q.Q_CHECKPOINT_EDGES, op="checkpoint.edges").result_set
        # Canonical properties include lineage, status, timestamps and edge authority.
        parts = [sorted(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
                 for rows in (nodes, edges)]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()

    def _verify(self, graph, fingerprint, *, healthy=True):
        if self._fingerprint(graph) != fingerprint:
            raise Conflict("snapshot verification failed; keep writers stopped")
        if healthy and check_invariants(self.db, graph, expected_tenant=self.tenant):
            raise Conflict("snapshot invariants failed; keep writers stopped")

    def list(self):
        entries = []
        for name, raw in self.connection.hgetall(self.index).items():
            name = name.decode() if isinstance(name, bytes) else name
            checkpoint_graph_name(self.tenant, name)
            entries.append({"name": name, **json.loads(raw)})
        return sorted(entries, key=lambda entry: entry["name"])

    def pending(self):
        raw = self.connection.get(self.key)
        return json.loads(raw) if raw else None

    def mutex_status(self):
        return {"held": bool(self.connection.exists(lock_key(self.main)))}

    def release_mutex(self, *, confirmed=False):
        if not confirmed:
            raise InvalidArgument("explicit stranded mutex release confirmation required")
        self._ready()
        if self.pending():
            raise Conflict("complete pending recovery before releasing the quota mutex")
        key = lock_key(self.main)
        owner = self.connection.get(key)
        if owner is None:
            return {"released": False, "held": False}
        if self._durable("EVAL", _UNLOCK, 1, key, owner) != 1:
            raise Conflict("quota mutex owner changed; keep writers stopped")
        return {"released": True, "held": False}

    def _reserve(self, journal):
        self._ready()
        journal["operation_id"] = secrets.token_hex(16)
        raw = json.dumps(journal, sort_keys=True, separators=(",", ":"))
        if not self._durable("SET", self.key, raw, "NX"):
            raise Conflict("pending recovery operation; keep writers stopped and run recover")
        return raw

    def _clear(self, raw):
        if self._durable("EVAL", _UNLOCK, 1, self.key, raw) != 1:
            raise Conflict("recovery journal changed; keep writers stopped")

    def _record(self, name, fingerprint, kind):
        metadata = json.dumps({"fingerprint": fingerprint, "kind": kind,
                               "created_at": int(time.time() * 1000)}, sort_keys=True)
        if not self._durable("HSETNX", self.index, name, metadata):
            existing = json.loads(self.connection.hget(self.index, name))
            if existing["fingerprint"] != fingerprint or existing["kind"] != kind:
                raise Conflict("checkpoint metadata changed; keep writers stopped")

    def _capacity(self):
        if self.connection.hlen(self.index) >= MAX_CHECKPOINTS:
            raise Conflict("checkpoint capacity reached; explicitly drop an old snapshot")

    def create(self, name):
        destination = checkpoint_graph_name(self.tenant, name)
        if self._exists(destination) or self.connection.hexists(self.index, name):
            raise Conflict("checkpoint exists; snapshots are immutable")
        self._capacity()
        fingerprint = self._fingerprint(self.main)
        self._verify(self.main, fingerprint)
        journal = {"op": "create", "name": name, "fingerprint": fingerprint}
        raw = self._reserve(journal)
        try:
            # A different offline command could finish between preflight and NX.
            self._capacity()
            if self._exists(destination) or self.connection.hexists(self.index, name):
                raise Conflict("checkpoint exists; snapshots are immutable")
        except Conflict:
            self._clear(raw)
            raise
        return self._complete(journal, raw)

    def drop(self, name):
        checkpoint_graph_name(self.tenant, name)
        if not self.connection.hexists(self.index, name):
            raise NotFoundInGraph("checkpoint not found")
        journal = {"op": "drop", "name": name}
        return self._complete(journal, self._reserve(journal))

    def restore(self, name):
        source = checkpoint_graph_name(self.tenant, name)
        metadata = self.connection.hget(self.index, name)
        if not metadata:
            raise NotFoundInGraph("checkpoint not found")
        expected = json.loads(metadata)["fingerprint"]
        self._verify(source, expected)
        before = self._fingerprint(self.main) if self._exists(self.main) else None
        if before is not None:
            self._capacity()
        rollback = "rollback-" + secrets.token_hex(8) if before is not None else None
        journal = {"op": "restore", "name": name, "fingerprint": expected,
                   "before": before, "rollback": rollback,
                   "stage": "stage-" + secrets.token_hex(8)}
        raw = self._reserve(journal)
        try:
            if before is not None:
                self._capacity()
        except Conflict:
            self._clear(raw)
            raise
        return self._complete(journal, raw)

    def recover(self, *, rollback=False):
        self._ready()
        raw = self.connection.get(self.key)
        if not raw:
            raise NotFoundInGraph("no pending recovery operation")
        raw = raw.decode() if isinstance(raw, bytes) else raw
        journal = json.loads(raw)
        if rollback and journal["op"] != "restore":
            raise InvalidArgument("rollback is only available for restore")
        if rollback and journal.get("before") is None:
            raise InvalidArgument("no previous main graph; complete recovery instead of deleting restored data")
        if rollback and not journal.get("recover_previous"):
            backup = checkpoint_graph_name(self.tenant, journal["rollback"])
            candidate = backup if self._exists(backup) else self.main
            # A forensic backup may be unhealthy. Reject before persisting a
            # direction that could never complete, leaving forward repair usable.
            self._verify(candidate, journal["before"])
            # Persist the operator's direction before replacing anything. A later
            # plain recover must finish rollback even after another lost reply.
            journal["recover_previous"] = True
            updated = json.dumps(journal, sort_keys=True, separators=(",", ":"))
            changed = self._durable(
                "EVAL", "if redis.call('get',KEYS[1]) == ARGV[1] then "
                "redis.call('set',KEYS[1],ARGV[2]); return 1 else return 0 end",
                1, self.key, raw, updated,
            )
            if changed != 1:
                raise Conflict("recovery journal changed; keep writers stopped")
            raw = updated
        return self._complete(journal, raw, rollback=journal.get("recover_previous", False))

    def _complete(self, journal, raw, *, rollback=False):
        name = journal["name"]
        snapshot = checkpoint_graph_name(self.tenant, name)
        if journal["op"] == "drop":
            if self._exists(snapshot):
                self._durable("GRAPH.DELETE", snapshot)
            self._durable("HDEL", self.index, name)
        elif journal["op"] == "create":
            if not self._exists(snapshot):
                self._verify(self.main, journal["fingerprint"])
                self._durable("GRAPH.COPY", self.main, snapshot)
            self._verify(snapshot, journal["fingerprint"])
            self._record(name, journal["fingerprint"], "checkpoint")
        else:
            stage = checkpoint_graph_name(self.tenant, journal["stage"])
            backup = None
            if journal["before"] is not None:
                backup = checkpoint_graph_name(self.tenant, journal["rollback"])
                if not self._exists(backup):
                    self._verify(self.main, journal["before"], healthy=False)
                    self._durable("GRAPH.COPY", self.main, backup)
                # Preserve an unhealthy live graph for forensics while repairing it.
                self._verify(backup, journal["before"], healthy=False)
                self._record(journal["rollback"], journal["before"], "rollback")
            wanted = journal["before"] if rollback else journal["fingerprint"]
            source = backup if rollback else snapshot
            self._verify(source, wanted)
            if self._exists(stage):
                # A prior interrupted attempt may have staged the opposite choice.
                self._durable("GRAPH.DELETE", stage)
            self._durable("GRAPH.COPY", source, stage)
            self._verify(stage, wanted)
            self._durable("RENAME", stage, self.main)
            self._verify(self.main, wanted)
        self._clear(raw)
        return {"operation": journal["op"], "name": name,
                "rollback": journal.get("rollback"), "recovered_previous": rollback}
