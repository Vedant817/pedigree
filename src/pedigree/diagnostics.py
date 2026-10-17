"""Public error envelopes and diagnostics that never format exception values."""
from __future__ import annotations

import logging
import re
import traceback
import uuid
from pathlib import Path

from .errors import PedigreeError

_MESSAGES = {
    "invalid_argument": "invalid argument", "unauthorized": "invalid or missing credential",
    "forbidden": "operation forbidden", "not_in_graph": "node not found",
    "conflict": "operation conflicts with current state", "too_large": "request too large",
    "rate_limited": "rate limited", "quota_exceeded": "node cap exceeded",
    "timeout": "operation timed out", "unavailable": "service unavailable",
}
_NUMERIC_DETAILS = frozenset({"limit", "cap", "nodes", "got", "count", "max", "min", "retry_after"})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
_log = logging.getLogger("pedigree.errors")


def _correlation_id(value=None) -> str:
    """Accept only an internal UUID; callers must not pass request header values."""
    if isinstance(value, str):
        try:
            return uuid.UUID(value).hex
        except ValueError:
            pass
    return uuid.uuid4().hex


correlation_id = _correlation_id


def error_payload(exc: PedigreeError, correlation_id=None) -> dict:
    if exc.code == "internal":
        return unexpected_error(exc, "typed_internal", correlation_id)
    # Typed exceptions can still contain caller data in message/detail. Only fixed
    # messages and reviewed numeric details cross the public boundary.
    details = {}
    if isinstance(exc.detail, dict):
        details = {key: value for key, value in exc.detail.items()
                   if key in _NUMERIC_DETAILS and type(value) in (int, float) and abs(value) < 10**15}
    return {"code": exc.code, "message": _MESSAGES.get(exc.code, "operation failed"),
            "detail": details or None, "correlation_id": _correlation_id(correlation_id)}


def unexpected_error(exc: BaseException, operation: str, correlation_id=None) -> dict:
    cid = _correlation_id(correlation_id)
    cls = type(exc).__name__
    cls = cls if _IDENTIFIER.fullmatch(cls) and "ped_" not in cls else "Exception"
    operation = operation if _IDENTIFIER.fullmatch(operation) and "ped_" not in operation else "operation"
    # Do not format exception messages, chained causes, source lines or locals.
    frames = [{"file": Path(frame.filename).name, "line": frame.lineno}
              for frame in traceback.extract_tb(exc.__traceback__)[-12:]]
    _log.error("operation=%s exception=%s correlation_id=%s frames=%s", operation, cls, cid, frames)
    return {"code": "internal", "correlation_id": cid}


_SAFE_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def validation_summary(exc) -> list[dict]:
    """Field paths and failure types for a request-validation error.

    Only identifier-shaped path segments and fixed error types survive: the
    submitted value and the validator message can both carry caller data.
    """
    summary = []
    for error in list(exc.errors())[:16]:
        parts = []
        for segment in error.get("loc", ()):
            if isinstance(segment, bool) or not isinstance(segment, (str, int)):
                parts.append("<key>")
            elif isinstance(segment, str) and not _SAFE_SEGMENT.fullmatch(segment):
                parts.append("<key>")
            else:
                parts.append(str(segment))
        summary.append({"at": ".".join(parts) or "<body>",
                        "type": str(error.get("type", "unknown"))[:64]})
    return summary


def log_validation_failure(correlation_id, exc) -> None:
    """Make a 422 diagnosable from the correlation id without widening the envelope."""
    _log.info("operation=request_validation correlation_id=%s errors=%s",
              _correlation_id(correlation_id), validation_summary(exc))


def log_typed_rejection(correlation_id, exc: PedigreeError) -> None:
    """Server-side reason for an authored 422; the public envelope stays opaque.

    `reason` is the static message written at the raise site (every raise site was
    audited 2026-10-17); `fields` are identifier-shaped `detail` keys. `detail`
    values are caller data and are never logged.
    """
    if exc.code != "invalid_argument":
        return
    reason = str(exc.args[0]) if exc.args else ""
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    fields = sorted(key for key in detail
                    if isinstance(key, str) and _SAFE_SEGMENT.fullmatch(key))[:16]
    _log.info("operation=typed_rejection code=invalid_argument correlation_id=%s "
              "reason=%r fields=%s", _correlation_id(correlation_id), reason[:200], fields)
