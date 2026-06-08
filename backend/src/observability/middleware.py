"""FastAPI request-logging middleware (task-011, overview §7).

Logs ONE structured event per request — method, path, status, duration_ms — via
the hygiene logger. It NEVER reads or logs the request/response body, headers, or
query string values (which can carry secrets/PII); only the route path template
shape and timing aggregates. Raw content cannot leak because the body is never
touched.
"""

import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from observability.logging import log_event

_MS_PER_SECOND = 1000

RequestHandler = Callable[[Request], Awaitable[Response]]


async def log_requests(request: Request, call_next: RequestHandler) -> Response:
    """Time the request and emit an aggregate-only structured log line."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * _MS_PER_SECOND, 2)
    log_event(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response
