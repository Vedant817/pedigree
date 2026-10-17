"""Bounded, thread-safe admission shared by one REST/MCP server instance."""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from .errors import RateLimited


class RateLimiter:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 read_limit: int = 120, write_limit: int = 120,
                 destructive_limit: int = 10, auth_limit: int = 10,
                 window: float = 60, max_keys: int = 4096):
        if any(type(value) is not int or value < 1 for value in
               (read_limit, write_limit, destructive_limit, auth_limit, max_keys)):
            raise ValueError('rate capacities must be positive integers')
        if not isinstance(window, (int, float)) or not math.isfinite(window) or window <= 0:
            raise ValueError('rate window must be positive')
        self.clock, self.window, self.max_keys = clock, window, max_keys
        self.read_limit, self.write_limit = read_limit, write_limit
        self.destructive_limit, self.auth_limit = destructive_limit, auth_limit
        self._buckets: dict[tuple[str, ...], deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for key, samples in list(self._buckets.items()):
            while samples and samples[0] <= now - self.window:
                samples.popleft()
            if not samples:
                del self._buckets[key]

    def _reject(self, now: float, expiry: float, limit: int) -> None:
        raise RateLimited('rate limited', detail={
            'limit': limit, 'retry_after': max(1, math.ceil(expiry - now))})

    def _reserve(self, entries: list[tuple[tuple[str, ...], int]], now: float) -> None:
        # Check every constraint before creating buckets or appending any sample.
        blocked = [(self._buckets[key][0] + self.window, limit) for key, limit in entries
                   if key in self._buckets and len(self._buckets[key]) >= limit]
        if blocked:
            expiry, limit = max(blocked)
            self._reject(now, expiry, limit)
        missing = sum(key not in self._buckets for key, _ in entries)
        if len(self._buckets) + missing > self.max_keys:
            expiry = min((samples[-1] + self.window for samples in self._buckets.values()), default=now + self.window)
            self._reject(now, expiry, self.max_keys)
        for key, _ in entries:
            self._buckets.setdefault(key, deque()).append(now)

    def check_peer(self, peer: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            samples = self._buckets.get(('auth', peer))
            if samples is not None and len(samples) >= self.auth_limit:
                self._reject(now, samples[0] + self.window, self.auth_limit)

    def failed_auth(self, peer: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune(now)
            self._reserve([(('auth', peer), self.auth_limit)], now)

    def admit(self, tenant: str, operation: str, *, dry_run: bool = False,
              record: bool = False) -> None:
        if operation in ('revoke', 'reinstate'):
            bucket = 'read' if dry_run else 'write'
            destructive = True
        elif operation == 'gate':
            bucket, destructive = ('write' if record else 'read'), False
        elif operation == 'whatif':
            bucket, destructive = 'write', False
        elif operation in ('read', 'write'):
            bucket, destructive = operation, False
        else:
            raise ValueError('unknown rate operation')
        entries = [(('tenant', tenant, bucket), self.read_limit if bucket == 'read' else self.write_limit)]
        if destructive:
            entries.append((('tenant', tenant, 'destructive'), self.destructive_limit))
        with self._lock:
            now = self.clock()
            self._prune(now)
            self._reserve(entries, now)
