"""Observability domain (task-011): structured JSON logs + log hygiene.

Public surface (CONVENTIONS: cross-module via service functions):
- `configure_logging()` / `log_event()` — JSON logging + aggregate-only hygiene.
- `log_requests` — FastAPI request-logging middleware.
- `register_celery_logging()` — Celery task lifecycle logging.
"""

from observability.celery_logging import register_celery_logging
from observability.logging import configure_logging, log_event
from observability.middleware import log_requests

__all__ = [
    "configure_logging",
    "log_event",
    "log_requests",
    "register_celery_logging",
]
