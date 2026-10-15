"""Typed error model. Every layer raises PedigreeError subclasses with a stable `code`.

REST maps codes to HTTP statuses; MCP returns {"error": {"code", "message", "detail"}}.
Client-facing messages never contain stack traces (docs/01 section 7.1).
"""

from __future__ import annotations

HTTP_STATUS: dict[str, int] = {
    "invalid_argument": 422,
    "unauthorized": 401,
    "forbidden": 403,
    "not_in_graph": 404,
    "conflict": 409,
    "too_large": 413,
    "rate_limited": 429,
    "quota_exceeded": 429,
    "timeout": 504,
    "unavailable": 503,
    "internal": 500,
}


class PedigreeError(Exception):
    code: str = "internal"

    def __init__(self, message: str, *, detail=None, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            if code not in HTTP_STATUS:
                raise ValueError(f"unknown error code {code!r}")
            self.code = code
        self.detail = detail

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]

    def to_dict(self) -> dict:
        out: dict = {"code": self.code, "message": str(self)}
        if self.detail is not None:
            out["detail"] = self.detail
        return {"error": out}


class InvalidArgument(PedigreeError):
    code = "invalid_argument"


class Unauthorized(PedigreeError):
    code = "unauthorized"


class Forbidden(PedigreeError):
    code = "forbidden"


class NotFoundInGraph(PedigreeError):
    code = "not_in_graph"


class Conflict(PedigreeError):
    code = "conflict"


class TooLarge(PedigreeError):
    code = "too_large"


class RateLimited(PedigreeError):
    code = "rate_limited"


class QuotaExceeded(PedigreeError):
    code = "quota_exceeded"


class QueryTimeout(PedigreeError):
    code = "timeout"


class Unavailable(PedigreeError):
    code = "unavailable"
