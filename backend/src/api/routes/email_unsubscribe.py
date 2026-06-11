"""Unsubscribe router — GET /email/unsubscribe?token=... (TASK-069).

Unauthenticated endpoint: the signed JWT token (audience
`trendpulse:unsubscribe`, server `jwt_secret`) is the sole credential — the
link must work from any mail client without a login.

Idempotent: sets `users.lifecycle_emails_opt_out = True`; a repeat click is a
no-op returning the same friendly HTML. Transactional emails
(verify/reset/renewal) are NOT affected by this flag.

Security (стадия 5.5 обязательна — task doc):
- Signature + audience + expiry checked via `parse_unsubscribe_token`;
  garbage/tampered/expired/foreign-audience all → the SAME 400 error-envelope
  (TASK-030), no reason details, no user enumeration.
- A valid token for a deleted user → the same success HTML (idempotent no-op;
  responding 4xx would leak account existence).
- Rate-limit: per-route override `unsubscribe_rate_limit_per_minute` (lower
  than the default auth'd budget — endpoint is unauthenticated; pattern:
  feedback router, TASK-042).
- GET with one targeted side effect (the flag) — known one-click compromise:
  a mail prefetcher may unsubscribe the link owner; accepted risk (task doc).
- No PII in logs: only user_id; the token/email never reach a logger.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST

from api.errors import ErrorCode, build_error_response
from api.rate_limit import limiter
from config import get_settings
from notifications.lifecycle import UnsubscribeTokenError, parse_unsubscribe_token
from storage.database import get_session
from storage.models.users import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])

# Minimal confirmation page — EN-only, Foresignal brand (TASK-072), no external
# resources, no reflected input (static string → no XSS surface).
_HTML_UNSUBSCRIBED = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Unsubscribed</title></head>
<body>
<p>You have been unsubscribed from Foresignal lifecycle emails.</p>
<p>Transactional emails (verification, password reset, billing) are not affected.</p>
</body>
</html>"""


def _unsubscribe_rate_limit() -> str:
    """Per-route limit string for the unauthenticated unsubscribe endpoint."""
    return f"{get_settings().unsubscribe_rate_limit_per_minute}/minute"


def get_db_session() -> Iterator[Session]:
    """Yield a committing sync session (pattern: feedback router)."""
    with get_session() as session:
        yield session


@router.get("/unsubscribe", response_class=HTMLResponse, response_model=None)
@limiter.limit(_unsubscribe_rate_limit)
def unsubscribe(
    request: Request,
    token: str = Query(min_length=1),
    session: Session = Depends(get_db_session),
) -> HTMLResponse | JSONResponse:
    """Verify the signed token and idempotently opt the user out.

    Returns:
        200: HTML confirmation (also on repeat clicks and deleted users —
             idempotent, no enumeration).
        400: Unified error-envelope for ANY invalid/expired/tampered token.
    """
    try:
        user_id = parse_unsubscribe_token(token)
    except UnsubscribeTokenError:
        # Uniform 400 (TASK-030 envelope) — no reason details, no oracle.
        logger.info("unsubscribe: token rejected")
        return build_error_response(
            code=ErrorCode.VALIDATION,
            message="Invalid unsubscribe link.",
            status=HTTP_400_BAD_REQUEST,
        )

    user = session.scalars(select(User).where(User.id == user_id)).unique().one_or_none()
    if user is None:
        # Deleted account (GDPR, TASK-033) — nothing to opt out; same success
        # page as the happy path (no account-existence oracle).
        logger.info("unsubscribe: user already gone user_id=%s", user_id)
        return HTMLResponse(content=_HTML_UNSUBSCRIBED)

    if not user.lifecycle_emails_opt_out:
        user.lifecycle_emails_opt_out = True
        session.commit()
        logger.info("unsubscribe: opt-out set user_id=%s", user_id)
    else:
        logger.info("unsubscribe: already opted out user_id=%s", user_id)

    return HTMLResponse(content=_HTML_UNSUBSCRIBED)
