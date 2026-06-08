"""`GET /ready` — readiness probe (task-011, overview §7 / arch §5).

Readiness is distinct from `/health` liveness (task-001, in `api.main`): `/health`
stays a pure 200 and NEVER touches a backing service, while `/ready` actively
checks that the DB (a trivial `SELECT 1`) and Redis (`PING`) are reachable. Both
ok -> 200 `{"db":"ok","redis":"ok"}`; any unreachable -> 503 with that dependency
marked `"unreachable"`. The probe deliberately leaks NO internals (no exception
text, host, or DSN) — only `ok`/`unreachable` markers (security). Checks are best
left fast; the engine `pool_pre_ping` + Redis socket defaults bound them.
"""

from typing import Literal, TypedDict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from starlette.status import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from config import get_settings
from storage.database import engine

router = APIRouter(tags=["ops"])

_OK: Literal["ok"] = "ok"
_UNREACHABLE: Literal["unreachable"] = "unreachable"


class ReadyResponse(TypedDict):
    """Per-dependency readiness markers (no internal detail leaked)."""

    db: Literal["ok", "unreachable"]
    redis: Literal["ok", "unreachable"]


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


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness: 200 when DB+Redis reachable, else 503 with per-dep markers."""
    db_ok = _check_db()
    redis_ok = _check_redis()
    body: ReadyResponse = {
        "db": _OK if db_ok else _UNREACHABLE,
        "redis": _OK if redis_ok else _UNREACHABLE,
    }
    status_code = HTTP_200_OK if (db_ok and redis_ok) else HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=body)
