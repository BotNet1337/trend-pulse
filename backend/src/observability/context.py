"""Request-scoped correlation id context variable (TASK-024).

A single `request_id` (uuid4 string) is threaded through each HTTP request and
Celery task via a ContextVar so EVERY log record in the same logical operation
carries the same id — even code that only calls `logger.info(...)` directly.

This module intentionally does NOT import logging.py to avoid import cycles
(logging.py will import this module, not the other way around).
"""

import uuid
from contextvars import ContextVar, Token

# The contextvar that carries the current request/trace id.  Defaults to None
# so that code paths without a request context (e.g., startup) produce "-"
# in logs rather than crashing.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request id, or None if no context is active."""
    return request_id_var.get()


def set_request_id(value: str) -> "Token[str | None]":
    """Set the request id and return a reset token for cleanup.

    Always paired with ``reset_request_id(token)`` in a finally-block so the
    value does not leak across requests/tasks (Celery prefork safety).
    """
    return request_id_var.set(value)


def reset_request_id(token: "Token[str | None]") -> None:
    """Reset the contextvar to its previous state using the token from set_request_id."""
    request_id_var.reset(token)


def new_request_id() -> str:
    """Generate a fresh random uuid4 string (hyphenated canonical form)."""
    return str(uuid.uuid4())


def coerce_request_id(raw: str | None) -> str:
    """Validate *raw* as a uuid4; return it as-is if valid, else generate a new one.

    Security: any incoming X-Request-ID header that is not a canonical UUID is
    silently discarded and replaced with a server-generated id — prevents header
    injection (the client cannot influence the correlation id we trust).
    """
    if raw is not None:
        try:
            # uuid.UUID() validates format; we re-stringify for canonical form.
            validated = str(uuid.UUID(raw))
            return validated
        except ValueError:
            pass
    return new_request_id()
