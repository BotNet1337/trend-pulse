"""Feedback router — GET /feedback/{token} (TASK-042).

Unauthenticated endpoint: the signed token is the sole bearer credential.
One tap → UPSERT ``alert_feedback`` row (on conflict on alert_id, update
verdict + updated_at). Returns a minimal HTML "спасибо" response so the
browser shows something useful when the user clicks a Telegram button.

Security:
- HMAC-verified, exp-checked token (alerts.feedback_tokens.verify_feedback_token).
- Rate-limit: per-route override at ``feedback_rate_limit_per_minute`` (lower
  than the default auth'd API limit — this endpoint is unauthenticated).
- No enumeration: expired/tampered/garbage all return the same 400 (uniform
  error, no oracle).
- No open redirect: the response is plain HTML, no Location header.
- alert deleted by retention → 410 Gone (friendly HTML).
- user_id derived from the alert row (not the token) — the token only asserts
  alert_id + verdict. This prevents token reuse across accounts.

DB: uses a synchronous Session injected via the ``get_db_session`` dependency
(same pattern as alerts/watchlist routers). The UPSERT uses SQLAlchemy's
``postgresql_insert ... on_conflict_do_update`` with the constraint name
``uq_alert_feedback_alert_id``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from alerts.feedback_tokens import FeedbackTokenError, verify_feedback_token
from api.rate_limit import limiter
from config import get_settings
from observability.logging import log_event
from storage.database import get_session
from storage.models.alert_feedback import VERDICT_DOWN, VERDICT_UP, AlertFeedback
from storage.models.alerts import Alert
from storage.models.base import utcnow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Verdict mapping from string to smallint DB value.
_VERDICT_MAP: dict[str, int] = {"up": VERDICT_UP, "down": VERDICT_DOWN}

# HTML response templates — minimal, no external resources, plain UTF-8.
_HTML_THANKS = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Спасибо!</title></head>
<body><p>Спасибо за ваш отзыв! 🙏</p></body>
</html>"""

_HTML_EXPIRED = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Ссылка устарела</title></head>
<body><p>Ссылка устарела или недействительна.</p></body>
</html>"""

_HTML_GONE = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Алерт удалён</title></head>
<body><p>Алерт больше не существует.</p></body>
</html>"""


def _feedback_rate_limit() -> str:
    """Per-route rate limit string for the unauthenticated feedback endpoint."""
    return f"{get_settings().feedback_rate_limit_per_minute}/minute"


def get_db_session() -> Iterator[Session]:
    """Yield a committing sync session for the feedback route."""
    with get_session() as session:
        yield session


@router.get("/{token}", response_class=HTMLResponse)
@limiter.limit(_feedback_rate_limit)
def record_feedback(
    request: Request,
    token: str,
    session: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Verify signed token, UPSERT alert_feedback, return HTML 'спасибо'.

    Rate-limited at ``feedback_rate_limit_per_minute`` (default 30/min,
    per-IP via ``rate_limit_key``).

    Returns:
        200: Feedback recorded (or idempotent re-tap).
        400: Invalid/tampered/expired token (uniform — no oracle).
        404: Alert not found (FK gone — likely deleted by retention).
        410: Same as 404 but signals the resource is intentionally gone.
    """
    # --- Verify token (HMAC + expiry). ---
    settings = get_settings()
    try:
        payload = verify_feedback_token(token, jwt_secret=settings.jwt_secret)
    except FeedbackTokenError as exc:
        # Uniform response: expired and invalid both → 400.
        # Log the exc string (only "expired" or "invalid" — no secrets).
        logger.info("feedback: token rejected", extra={"reason": str(exc)})
        return HTMLResponse(content=_HTML_EXPIRED, status_code=400)

    alert_id = int(payload["alert_id"])
    verdict_str = str(payload["verdict"])

    # Map verdict string to smallint; reject unknown verdicts (defence-in-depth).
    verdict_int = _VERDICT_MAP.get(verdict_str)
    if verdict_int is None:
        logger.warning("feedback: unknown verdict in token", extra={"verdict": verdict_str})
        return HTMLResponse(content=_HTML_EXPIRED, status_code=400)

    # --- Look up the alert to get user_id (and confirm it still exists). ---
    alert = session.execute(select(Alert).where(Alert.id == alert_id)).scalar_one_or_none()
    if alert is None:
        return HTMLResponse(content=_HTML_GONE, status_code=410)

    user_id: int = alert.user_id
    now = utcnow()

    # --- UPSERT: insert or update verdict (last-write-wins). ---
    stmt = (
        pg_insert(AlertFeedback)
        .values(
            user_id=user_id,
            alert_id=alert_id,
            verdict=verdict_int,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_alert_feedback_alert_id",
            set_={"verdict": verdict_int, "updated_at": now},
        )
    )
    session.execute(stmt)
    session.commit()

    log_event(
        "alert_feedback_recorded",
        alert_id=alert_id,
        user_id=user_id,
        verdict=verdict_int,
    )

    # Funnel event (TASK-050): emit aggregate-only breadcrumb for feedback step.
    # Emitted on every feedback tap (not only "first" — aggregate SQL handles first-only).
    from analytics.constants import FUNNEL_FEEDBACK_GIVEN

    log_event(FUNNEL_FEEDBACK_GIVEN, alert_id=alert_id, user_id=user_id, verdict=verdict_int)

    return HTMLResponse(content=_HTML_THANKS, status_code=200)
