"""FastAPI request-logging middleware (task-011, overview §7; TASK-024 AC1).

Logs ONE structured event per request — method, path, status, duration_ms — via
the hygiene logger. It NEVER reads or logs the request/response body, headers, or
query string values (which can carry secrets/PII); only the route path template
shape and timing aggregates. Raw content cannot leak because the body is never
touched.

TASK-024: generates (or inherits a validated) ``request_id`` (uuid4), stores it
in the request-scoped contextvar for the duration of the call, and echoes it back
in the ``X-Request-ID`` response header. The ``RequestIdFilter`` attached by
``configure_logging`` ensures every log record emitted while the contextvar is
active carries the same id.
"""

import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from observability.context import coerce_request_id, reset_request_id, set_request_id
from observability.logging import log_event

_MS_PER_SECOND = 1000

RequestHandler = Callable[[Request], Awaitable[Response]]


async def log_requests(request: Request, call_next: RequestHandler) -> Response:
    """Time the request, bind a correlation id, and emit an aggregate log line.

    Steps (TASK-024):
    1. Accept the incoming ``X-Request-ID`` header if it is a valid uuid4;
       otherwise generate a fresh one (security: no header injection).
    2. Store the id in the request-scoped contextvar (set/finally-reset pattern).
    3. Call the next handler; record duration.
    4. Emit the aggregate log event (includes request_id via filter).
    5. Set ``X-Request-ID`` on the response so callers can correlate.
    """
    rid = coerce_request_id(request.headers.get("X-Request-ID"))
    token = set_request_id(rid)
    start = time.perf_counter()
    try:
        # If `call_next` raises (an error from deeper in the ASGI stack), let the
        # ORIGINAL exception propagate untouched — do NOT reference `response`
        # here, or an UnboundLocalError would mask the real error (the very thing
        # Sentry needs to see). The aggregate log + response header run only on the
        # success path; the contextvar is always reset in `finally`.
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * _MS_PER_SECOND, 2)
        log_event(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            request_id=rid,
        )
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        reset_request_id(token)
