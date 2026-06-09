"""`GET /ready` — readiness probe (task-011/task-023, overview §7 / arch §5).

Readiness is distinct from `/health` liveness (task-001, in `api.main`): `/health`
stays a pure 200 and NEVER touches a backing service, while `/ready` actively
checks that the DB (a trivial `SELECT 1`), Redis (`PING`), and the Celery worker
(`inspect().ping()` bounded by `celery_ping_timeout_seconds`) are reachable. All
ok -> 200 `{"db":"ok","redis":"ok","celery":"ok"}`; any unreachable -> 503 with
that dependency marked `"unreachable"`. The probe deliberately leaks NO internals
(no exception text, host, or DSN) — only `ok`/`unreachable` markers (security).
Checks are best left fast and bounded (socket/control-bus timeouts, task-011/023).
"""

from typing import Literal, TypedDict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from starlette.status import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from celery_app import celery_app
from config import get_settings
from storage.database import engine

router = APIRouter(tags=["ops"])

_OK: Literal["ok"] = "ok"
_UNREACHABLE: Literal["unreachable"] = "unreachable"


class ReadyResponse(TypedDict):
    """Per-dependency readiness markers (no internal detail leaked)."""

    db: Literal["ok", "unreachable"]
    redis: Literal["ok", "unreachable"]
    celery: Literal["ok", "unreachable"]


def _check_db() -> bool:
    """True if a trivial `SELECT 1` succeeds against the configured engine."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        # Swallow the specific error: readiness must not leak DSN/exception text
        # (security). The 503 marker is enough for the orchestrator.
        return False


def _check_redis() -> bool:
    """True if Redis answers a `PING` within the readiness timeout.

    Short-lived client bounded by `readiness_check_timeout_seconds` so a stalled
    (not refused) Redis cannot hang the probe.
    """
    settings = get_settings()
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.readiness_check_timeout_seconds,
            socket_timeout=settings.readiness_check_timeout_seconds,
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:
        return False


def _check_celery() -> bool:
    """True if at least one Celery worker responds to a control-bus ping.

    Uses `inspect(timeout=...).ping()` bounded by `celery_ping_timeout_seconds`
    so the probe cannot hang on a slow/stalled control channel (same principle as
    `_check_redis` socket bounds). Returns False on any exception — including
    timeout, connection error, or broker unavailability — so the probe is always
    bounded. Leaks no internal detail (same `ok`/`unreachable` contract as db/redis).
    """
    settings = get_settings()
    try:
        result = celery_app.control.inspect(
            timeout=float(settings.celery_ping_timeout_seconds)
        ).ping()
        # `ping()` returns a dict of {worker_name: {"ok": "pong"}} for live workers,
        # or None/empty dict when no workers respond within the timeout.
        return bool(result)
    except Exception:
        return False


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness: 200 when DB+Redis+Celery reachable, else 503 with per-dep markers."""
    db_ok = _check_db()
    redis_ok = _check_redis()
    celery_ok = _check_celery()
    body: ReadyResponse = {
        "db": _OK if db_ok else _UNREACHABLE,
        "redis": _OK if redis_ok else _UNREACHABLE,
        "celery": _OK if celery_ok else _UNREACHABLE,
    }
    status_code = (
        HTTP_200_OK if (db_ok and redis_ok and celery_ok) else HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=body)
