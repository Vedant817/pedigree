"""FalkorDB access layer: one connection factory, one query helper, one trace.

Design rules (docs/02 section 4):
- every graph mutation is one query; no MULTI/EXEC anywhere;
- reads use `ro_query` with a timeout, writes use `query` with a timeout;
- every op appends `{op, ms, rows}` to the caller's Trace (judging requirement);
- DB errors are mapped to typed PedigreeError codes without leaking internals.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from falkordb import FalkorDB

from ..config import LIMITS, Settings, get_settings
from ..errors import Conflict, Forbidden, PedigreeError, QueryTimeout, Unavailable

CHUNK = LIMITS["chunk"]


# --- error mapping ----------------------------------------------------------
def _exc_types() -> tuple[type[Exception], ...]:
    types: list[type[Exception]] = []
    try:  # falkordb re-exports redis exceptions
        from falkordb import exceptions as fex  # type: ignore[attr-defined]

        for name in ("ResponseError", "NoPermissionError", "ConnectionError", "TimeoutError"):
            t = getattr(fex, name, None)
            if isinstance(t, type) and issubclass(t, Exception):
                types.append(t)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        from redis import exceptions as rex  # type: ignore

        for name in ("ResponseError", "NoPermissionError", "ConnectionError", "TimeoutError"):
            t = getattr(rex, name, None)
            if isinstance(t, type) and issubclass(t, Exception) and t not in types:
                types.append(t)
    except Exception:  # pragma: no cover - defensive
        pass
    if not types:  # bare fallback: never crash at import time
        types.append(Exception)
    return tuple(types)


DB_EXC: tuple[type[Exception], ...] = _exc_types()


def map_db_error(exc: Exception) -> PedigreeError:
    msg = str(exc)
    low = msg.lower()
    # Verified raw message (v4.22.1): "unique constraint violation on node of type Node"
    if "unique constraint" in low or "constraint violation" in low:
        return Conflict("an entity with this id already exists")
    if "timeout" in low or "timed out" in low:
        return QueryTimeout("query timed out")
    if "permission" in low:
        return Forbidden("not permitted for this tenant")
    if "connection" in low or "refused" in low or "unavailable" in low:
        return Unavailable("database unavailable")
    return PedigreeError("database error", detail={"type": type(exc).__name__})


# --- trace ------------------------------------------------------------------
@dataclass
class TraceEntry:
    op: str
    ms: float
    rows: int

    def as_dict(self) -> dict:
        return {"op": self.op, "ms": round(self.ms, 2), "rows": self.rows}


@dataclass
class Trace:
    """Per-request trace: the judge-facing 'tool/args/ms/rows' strip (docs/02 section 5)."""

    entries: list[TraceEntry] = field(default_factory=list)

    def add(self, op: str, ms: float, rows: int) -> None:
        self.entries.append(TraceEntry(op=op, ms=ms, rows=rows))

    def as_list(self) -> list[dict]:
        return [e.as_dict() for e in self.entries]

    @property
    def total_ms(self) -> float:
        return round(sum(e.ms for e in self.entries), 2)


def chunks(xs: Sequence[Any] | Iterable[Any], n: int = CHUNK) -> Iterator[list[Any]]:
    """Split a sequence into lists of at most n items (chunked writes per docs/02 section 4)."""
    buf: list[Any] = []
    for x in xs:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


# --- connection -------------------------------------------------------------
class Db:
    """FalkorDB access with **one connection per thread**.

    The FastAPI threadpool and the eval/concurrency suites drive many threads through one
    `Db` instance; a single shared connection serialises them and turns load into timeouts
    (measured in `tests/integration/test_isolation_concurrency.py`: 160 writers on one
    connection produced `unavailable`). Connections are created lazily per thread and dropped
    again by `reset()`.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._local = threading.local()

    @property
    def client(self) -> FalkorDB:
        client = getattr(self._local, "client", None)
        if client is None:
            client = FalkorDB(
                host=self.settings.falkor_host,
                port=self.settings.falkor_port,
                username=self.settings.falkor_username or None,
                password=self.settings.falkor_password or None,
            )
            self._local.client = client
        return client

    def select(self, gname: str):
        return self.client.select_graph(gname)

    def reset(self) -> None:
        """Drop this thread's cached connection (tests / connection recovery)."""
        self._local = threading.local()

    # -- introspection -------------------------------------------------------
    def ping(self) -> bool:
        try:
            return bool(self.client.connection.ping())
        except Exception:
            self.reset()
            return False

    def module_version(self) -> int | None:
        """Version of the `graph` module (42201 for FalkorDB v4.22.1).

        MODULE LIST arrives either as dicts (redis-py parsed) or as flat
        key/value lists (falkordb client passthrough: ['name','graph','ver',42201,...]);
        handle both shapes.
        """
        rows = self.client.connection.execute_command("MODULE", "LIST")
        for row in rows or []:
            if isinstance(row, dict):
                info = dict(row)
            else:
                row_list = list(row)
                info = {
                    row_list[i]: row_list[i + 1]
                    for i in range(0, len(row_list) - 1, 2)
                }
            info = {
                (k.decode() if isinstance(k, bytes) else k): v for k, v in info.items()
            }
            if info.get("name") == "graph":
                ver = info.get("ver")
                return int(ver) if ver is not None else None
        return None

    def list_graphs(self) -> list[str]:
        out = []
        for g in self.client.list_graphs():
            out.append(g.decode() if isinstance(g, bytes) else g)
        return out

    # -- queries -------------------------------------------------------------
    def query(
        self,
        gname: str,
        cypher: str,
        params: dict | None = None,
        *,
        op: str = "query",
        timeout_ms: int | None = None,
        trace: Trace | None = None,
        write: bool = True,
    ):
        """Run one static, parameterised Cypher statement. Returns the raw result."""
        return self._run(gname, cypher, params, op=op, timeout_ms=timeout_ms, trace=trace, write=write)

    def ro_query(
        self,
        gname: str,
        cypher: str,
        params: dict | None = None,
        *,
        op: str = "query",
        timeout_ms: int | None = None,
        trace: Trace | None = None,
    ):
        return self._run(gname, cypher, params, op=op, timeout_ms=timeout_ms, trace=trace, write=False)

    def _run(
        self,
        gname: str,
        cypher: str,
        params: dict | None,
        *,
        op: str,
        timeout_ms: int | None,
        trace: Trace | None,
        write: bool,
    ):
        if timeout_ms is None:
            timeout_ms = self.settings.write_timeout_ms if write else self.settings.read_timeout_ms
        g = self.select(gname)
        t0 = time.perf_counter()
        try:
            if write:
                res = g.query(cypher, params or {}, timeout=timeout_ms)
            else:
                res = g.ro_query(cypher, params or {}, timeout=timeout_ms)
        except DB_EXC as exc:  # noqa: PERF203 - single boundary
            raise map_db_error(exc) from exc
        ms = (time.perf_counter() - t0) * 1000.0
        rows = len(res.result_set) if res.result_set else 0
        if trace is not None:
            trace.add(op, ms, rows)
        return res

    def execute_admin(self, *args: Any):
        """Raw command on the admin connection (GRAPH.CONSTRAINT, MODULE LIST, ...)."""
        try:
            return self.client.connection.execute_command(*args)
        except DB_EXC as exc:
            raise map_db_error(exc) from exc

    def admin_raw(self, *args: Any):
        """Unmapped raw command - for idempotent DDL where 'already exists' is expected."""
        return self.client.connection.execute_command(*args)

    def try_query(self, gname: str, cypher: str, params: dict | None = None):
        """Unmapped query - only for idempotent DDL. Returns (ok, error_message)."""
        try:
            self.select(gname).query(cypher, params or {})
            return True, ""
        except Exception as exc:  # noqa: BLE001 - DDL probe
            return False, str(exc)
