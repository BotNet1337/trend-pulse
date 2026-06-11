"""Lifecycle-email core (TASK-069): due-selection, digest content, senders, tokens.

Three lifecycle flows share this module:
  - **welcome** — event-driven (UserManager.on_after_verify), not scheduled here;
    this module only supplies the unsubscribe token/URL for its footer.
  - **weekly digest** — top-K delivered alerts of the user's week, ≤1 per
    `digest_period_days` (state: `users.digest_last_sent_at`).
  - **win-back** — one per inactivity cycle, hard-capped at one per
    `WINBACK_COOLDOWN_DAYS` (state: `users.winback_last_sent_at`).

Anti-spam invariants (task doc Discussion — the core of the task):
  - Lifecycle emails go ONLY to `is_verified=True` AND `lifecycle_emails_opt_out=False`.
  - Every lifecycle email carries an unsubscribe footer link + `List-Unsubscribe`.
  - Transactional emails (verify/reset/renewal) are NOT affected by opt-out.

The due-functions are pure (no DB, no clock) so the frequency-limit matrix is
unit-testable; callers pass aware UTC datetimes read from the `users` row.

Unsubscribe tokens reuse the stack's `fastapi_users.jwt` helpers (no new deps)
with a dedicated audience so auth JWTs can never unsubscribe anyone.

Compliance §7: digest content is sanitized topic labels + aggregate score/pack
only — never raw post text or channel handles (`textutils.sanitize_topic_label`,
same as trending/cases).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote

import jwt as pyjwt
from fastapi_users.jwt import decode_jwt, generate_jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import Settings, get_settings
from notifications.constants import (
    _DIGEST_SUBJECT,
    _DIGEST_TEMPLATE,
    _WINBACK_CTA_PATH,
    _WINBACK_SUBJECT,
    _WINBACK_TEMPLATE,
    UNSUBSCRIBE_API_PATH,
    UNSUBSCRIBE_TOKEN_AUDIENCE,
    UNSUBSCRIBE_TOKEN_LIFETIME_SECONDS,
)
from notifications.email import send_templated_email
from storage.models.alerts import DELIVERY_STATUS_DELIVERED, Alert
from storage.models.clusters import Cluster
from storage.models.watchlists import Watchlist
from textutils import sanitize_topic_label

if TYPE_CHECKING:
    from storage.models.users import User

logger = logging.getLogger(__name__)

# Scores in email copy are rendered with one decimal place; numbers cross the
# templates-service boundary as STRINGS (JSON-safe, no float-format surprises).
_SCORE_DECIMAL_PLACES = 1

# Email header advertising one-click unsubscribe (RFC 2369). Mail clients show
# a native "unsubscribe" affordance; the footer link covers the rest.
_LIST_UNSUBSCRIBE_HEADER = "List-Unsubscribe"


# ---------------------------------------------------------------------------
# Pure due-selection (unit-tested frequency limits)
# ---------------------------------------------------------------------------


def is_digest_due(
    *,
    now: datetime,
    is_verified: bool,
    opt_out: bool,
    digest_last_sent_at: datetime | None,
    period_days: int,
) -> bool:
    """Whether a weekly digest may be sent to this user at `now`.

    Pure: all state comes from arguments. The frequency limit is
    «≤ 1 digest per `period_days`», measured from the persisted
    `digest_last_sent_at` (never from the beat schedule — restart-safe).

    Note: content emptiness (0 delivered alerts → skip) is the CALLER's check;
    this function only answers the eligibility/frequency question.
    """
    if not is_verified or opt_out:
        return False
    if digest_last_sent_at is None:
        return True
    return now - digest_last_sent_at >= timedelta(days=period_days)


def is_winback_due(
    *,
    now: datetime,
    is_verified: bool,
    opt_out: bool,
    has_watchlist: bool,
    last_delivered_at: datetime | None,
    winback_last_sent_at: datetime | None,
    inactive_days: int,
    cooldown_days: int,
) -> bool:
    """Whether a win-back email may be sent to this user at `now`.

    Inactivity surrogate (no open tracking — delivery is Telegram-side):
    `last_delivered_at` = MAX(alerts.delivered_at) for the user; None = no
    delivered alerts at all. A user with no watchlist is never targeted
    (nothing to win them back to).

    Frequency model («≤1 per cycle» AND «not more often than `cooldown_days`»):
      - first win-back: any time once inactive;
      - repeat win-back: requires a NEW inactivity cycle (re-arm = some
        delivery happened AFTER the previous win-back) AND the hard cooldown
        elapsed. Both conditions, conservatively ANDed — with no new activity
        the user gets exactly one win-back ever.
    """
    if not is_verified or opt_out or not has_watchlist:
        return False

    inactive = last_delivered_at is None or (
        now - last_delivered_at >= timedelta(days=inactive_days)
    )
    if not inactive:
        return False

    if winback_last_sent_at is None:
        return True

    rearmed = last_delivered_at is not None and last_delivered_at > winback_last_sent_at
    cooldown_elapsed = now - winback_last_sent_at >= timedelta(days=cooldown_days)
    return rearmed and cooldown_elapsed


# ---------------------------------------------------------------------------
# Unsubscribe token (fastapi-users JWT helpers — no new dependencies)
# ---------------------------------------------------------------------------


class UnsubscribeTokenError(ValueError):
    """Raised when an unsubscribe token is invalid, expired, or foreign.

    Deliberately carries no reason details — the API responds with a uniform
    400 regardless (no oracle / no user enumeration).
    """


def generate_unsubscribe_token(user_id: int, *, settings: Settings | None = None) -> str:
    """Sign a long-lived unsubscribe token for `user_id`.

    Audience is `UNSUBSCRIBE_TOKEN_AUDIENCE` (never the auth audience) and the
    secret is the existing server `jwt_secret` — same trust root, distinct use.
    """
    cfg = settings or get_settings()
    return generate_jwt(
        {"sub": str(user_id), "aud": UNSUBSCRIBE_TOKEN_AUDIENCE},
        cfg.jwt_secret,
        lifetime_seconds=UNSUBSCRIBE_TOKEN_LIFETIME_SECONDS,
    )


def parse_unsubscribe_token(token: str, *, settings: Settings | None = None) -> int:
    """Verify an unsubscribe token and return the embedded user id.

    Raises:
        UnsubscribeTokenError: signature/audience/expiry/shape failure —
            uniformly, with no distinguishing detail (no enumeration oracle).
    """
    cfg = settings or get_settings()
    try:
        payload = decode_jwt(token, cfg.jwt_secret, audience=[UNSUBSCRIBE_TOKEN_AUDIENCE])
    except pyjwt.PyJWTError as exc:
        raise UnsubscribeTokenError("invalid unsubscribe token") from exc
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.isdigit():
        raise UnsubscribeTokenError("invalid unsubscribe token")
    return int(sub)


def build_unsubscribe_url(user_id: int, *, settings: Settings | None = None) -> str:
    """Absolute unsubscribe URL for the given user (footer link + header).

    Base: `public_base_url` (same source as feedback-button URLs, TASK-042);
    empty → fall back to `frontend_base_url`, which points at the same nginx
    edge that proxies `/api/` (dev default `http://localhost`). The path is the
    CLIENT-facing `/api/v1/...` form (nginx strips `/api/`).
    """
    cfg = settings or get_settings()
    base = cfg.public_base_url or cfg.frontend_base_url
    token = generate_unsubscribe_token(user_id, settings=cfg)
    return f"{base}{UNSUBSCRIBE_API_PATH}?token={quote(token)}"


def list_unsubscribe_headers(unsubscribe_url: str) -> dict[str, str]:
    """`List-Unsubscribe` header dict for a lifecycle email (RFC 2369 form)."""
    return {_LIST_UNSUBSCRIBE_HEADER: f"<{unsubscribe_url}>"}


# ---------------------------------------------------------------------------
# Digest content
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DigestItem:
    """One digest row: sanitized topic label + score + optional pack slug."""

    topic: str
    score: float
    pack_slug: str | None


def collect_digest_items(
    session: Session,
    *,
    user_id: int,
    now: datetime,
    top_k: int,
    period_days: int,
) -> list[DigestItem]:
    """Top-K delivered alerts of the user's last `period_days`, score DESC.

    Topic labels come from `clusters.topic` and are sanitized via
    `sanitize_topic_label` (compliance §7 — clusters.topic may contain raw post
    text; same guard as trending/cases). Pack signature: the user's watchlist
    rows matching the cluster topic supply `pack_slug` (NULL = manual list).

    Empty result ⇒ the caller MUST skip the digest (empty email = spam, AC2).
    """
    since = now - timedelta(days=period_days)
    rows = session.execute(
        select(Alert.score, Cluster.topic)
        .join(Cluster, Alert.cluster_id == Cluster.id)
        .where(Alert.user_id == user_id)
        .where(Alert.delivery_status == DELIVERY_STATUS_DELIVERED)
        .where(Alert.delivered_at.is_not(None))
        .where(Alert.delivered_at >= since)
        .order_by(Alert.score.desc())
        .limit(top_k)
    ).all()
    if not rows:
        return []

    topics = {topic for _, topic in rows}
    pack_rows = session.execute(
        select(Watchlist.topic, func.max(Watchlist.pack_slug))
        .where(Watchlist.user_id == user_id)
        .where(Watchlist.topic.in_(topics))
        .group_by(Watchlist.topic)
    ).all()
    pack_by_topic: dict[str, str | None] = {topic: slug for topic, slug in pack_rows}

    return [
        DigestItem(
            topic=sanitize_topic_label(topic),
            score=score,
            pack_slug=pack_by_topic.get(topic),
        )
        for score, topic in rows
    ]


# ---------------------------------------------------------------------------
# Senders (raise EmailRenderError/EmailSendError — caller handles best-effort)
# ---------------------------------------------------------------------------


def send_weekly_digest(
    *,
    user: User,
    items: list[DigestItem],
    settings: Settings | None = None,
) -> None:
    """Render + send the weekly digest. Caller guarantees `items` is non-empty.

    Props cross the templates-service boundary JSON-safe: scores are formatted
    as STRINGS (one decimal place). PII: logs carry only user_id/item count.
    """
    cfg = settings or get_settings()
    unsubscribe_url = build_unsubscribe_url(user.id, settings=cfg)
    props: dict[str, object] = {
        "userName": user.email,
        "items": [
            {
                "topic": item.topic,
                "score": f"{item.score:.{_SCORE_DECIMAL_PLACES}f}",
                "packSlug": item.pack_slug,
            }
            for item in items
        ],
        "dashboardUrl": f"{cfg.frontend_base_url}{_WINBACK_CTA_PATH}",
        "unsubscribeUrl": unsubscribe_url,
    }
    logger.info("sending weekly digest user_id=%s items=%s", user.id, len(items))
    send_templated_email(
        to=user.email,
        template=_DIGEST_TEMPLATE,
        subject=_DIGEST_SUBJECT,
        props=props,
        settings=cfg,
        headers=list_unsubscribe_headers(unsubscribe_url),
    )
    logger.info("weekly digest sent user_id=%s", user.id)


def send_winback(*, user: User, settings: Settings | None = None) -> None:
    """Render + send the win-back email («your packs have been quiet»).

    PII: logs carry only user_id — never email/token/URL.
    """
    cfg = settings or get_settings()
    unsubscribe_url = build_unsubscribe_url(user.id, settings=cfg)
    props: dict[str, object] = {
        "userName": user.email,
        "watchlistsUrl": f"{cfg.frontend_base_url}{_WINBACK_CTA_PATH}",
        "unsubscribeUrl": unsubscribe_url,
    }
    logger.info("sending win-back user_id=%s", user.id)
    send_templated_email(
        to=user.email,
        template=_WINBACK_TEMPLATE,
        subject=_WINBACK_SUBJECT,
        props=props,
        settings=cfg,
        headers=list_unsubscribe_headers(unsubscribe_url),
    )
    logger.info("win-back sent user_id=%s", user.id)
