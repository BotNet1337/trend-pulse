"""Unified API error types and response builder (TASK-030).

`ErrorCode` — machine-readable StrEnum; no magic literals on call-sites.
`build_error_response` — single builder that every exception-handler calls.

All 4xx/5xx responses from the API surface follow the envelope:
    {"error": {"code": "<ErrorCode>", "message": "<str>", "details?": [...]}}

The `details` field is only populated for 422 VALIDATION responses; it carries
normalised per-field error items `[{field: str, message: str}]` where the `field`
key is a dot-path with the Pydantic `body` prefix stripped.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorCode(StrEnum):
    """Machine-readable error codes — stable identifiers for the frontend.

    Mapped from exception types in `api.main` exception-handlers (centralised).
    No magic string literals on call-sites: always reference `ErrorCode.XXX`.
    """

    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    PLAN_LIMIT_EXCEEDED = "PLAN_LIMIT_EXCEEDED"
    FEATURE_NOT_AVAILABLE = "FEATURE_NOT_AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE = "DUPLICATE"
    VALIDATION = "VALIDATION"
    RATE_LIMITED = "RATE_LIMITED"
    BILLING_NOT_CONFIGURED = "BILLING_NOT_CONFIGURED"
    INTERNAL = "INTERNAL"


class _ValidationDetail(BaseModel):
    """Single field error item in a VALIDATION envelope."""

    field: str
    message: str


class _ErrorBody(BaseModel):
    """Inner error object."""

    code: ErrorCode
    message: str
    details: list[_ValidationDetail] | None = None


class _ErrorEnvelope(BaseModel):
    """Top-level error envelope: {error: {code, message, details?}}."""

    error: _ErrorBody


# HTTP status → ErrorCode mapping for generic HTTPException dispatch.
# PlanLimitExceeded (402/403) is handled separately (source-based, not status-based).
_HTTP_STATUS_TO_CODE: dict[int, ErrorCode] = {
    401: ErrorCode.UNAUTHORIZED,
    402: ErrorCode.PLAN_LIMIT_EXCEEDED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.DUPLICATE,
    429: ErrorCode.RATE_LIMITED,
}


def build_error_response(
    *,
    code: ErrorCode,
    message: str,
    status: int,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    """Construct the unified error JSON response.

    Args:
        code: Machine-readable `ErrorCode` member.
        message: Human-readable description (must not contain stack/SQL/paths).
        status: HTTP status code for the response.
        details: Optional list of `{field, message}` dicts (VALIDATION only).

    Returns:
        JSONResponse with the unified envelope body.
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=status, content={"error": body})


def http_status_to_code(status: int) -> ErrorCode:
    """Map an HTTP status code to an `ErrorCode`, defaulting to INTERNAL."""
    return _HTTP_STATUS_TO_CODE.get(status, ErrorCode.INTERNAL)


def normalize_validation_details(
    pydantic_errors: Sequence[Any],
) -> list[dict[str, str]]:
    """Convert Pydantic RequestValidationError detail items to envelope detail items.

    Input (Pydantic v2 format):
        [{"loc": ["body", "channel", "handle"], "msg": "...", "type": "..."}, ...]

    Output:
        [{"field": "channel.handle", "message": "..."}, ...]

    Normalisation rules:
    - `loc` prefix `body` is stripped (it is a Pydantic internal, not a field name).
    - Numeric path segments (list indices) are kept as-is in the dot-path.
    - Empty path after stripping → field = "root".
    """
    result: list[dict[str, str]] = []
    for item in pydantic_errors:
        loc: list[str | int] = list(item.get("loc", []))
        msg: str = str(item.get("msg", ""))
        # Strip leading "body" segment (Pydantic v2 wraps request body under "body").
        if loc and loc[0] == "body":
            loc = loc[1:]
        field_path = ".".join(str(p) for p in loc) if loc else "root"
        result.append({"field": field_path, "message": msg})
    return result
