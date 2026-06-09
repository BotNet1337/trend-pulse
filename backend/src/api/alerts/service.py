"""Alerts read service — tenant-scoped, read-only (TASK-016 C4 / TASK-020, CONVENTIONS).

Reads the `alerts` table joined with `clusters` for `topic`, applies the history
window from PLAN_LIMITS (billing seam), and returns a cursor-paginated AlertListResponse.
Every query is tenant-scoped on BOTH `Alert.user_id` and `Cluster.user_id`
(defense-in-depth: a cluster_id can never surface another tenant's topic).

Named constants (no magic literals):
- DEFAULT_ALERTS_PAGE_SIZE: default page size when `limit` not supplied.
- MAX_ALERTS_PAGE_SIZE: hard cap — requests above this are silently clamped.

History window comes exclusively from `PLAN_LIMITS[plan][Resource.HISTORY]` (days):
- Free (0 days) → returns empty list + history_unavailable=True.
- Pro (30 days) / Team (90 days) → filters by first_seen >= now - window.

Cursor format (TASK-020):
- Opaque base64url-encoded JSON: [first_seen_iso, id] (RFC 4648 URL-safe, no padding).
- Keyset: ORDER BY first_seen DESC, id DESC; WHERE (first_seen, id) < (cursor_fs, cursor_id).
- Invalid cursor → raises InvalidCursorError (router maps to 422).
"""

import base64
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import literal, select, tuple_
from sqlalchemy.orm import Session

from api.alerts.schemas import AlertListResponse, AlertRead
from billing.plans import PLAN_LIMITS, Plan, Resource
from storage.models.alerts import Alert
from storage.models.clusters import Cluster
from storage.models.users import User

# Pagination constants (no magic literals, CONVENTIONS).
DEFAULT_ALERTS_PAGE_SIZE: int = 20
MAX_ALERTS_PAGE_SIZE: int = 100

# Bounds for a decoded cursor `id`: `alerts.id` is a positive Postgres int8 serial.
# A crafted cursor carrying a huge/negative int would otherwise reach the DB and
# could raise an int8-overflow DataError (a 500) — instead we reject it as a
# malformed cursor (422), keeping the "bad cursor never 500s" invariant (AC3).
_MIN_CURSOR_ID: int = 0
_MAX_CURSOR_ID: int = 2**63 - 1


class InvalidCursorError(ValueError):
    """Raised when a cursor token cannot be decoded or fails validation.

    The router catches this and returns HTTP 422 (not 500).
    """


def _plan_history_days(user: User) -> int:
    """Return history window in days for the user's plan (0 = no history)."""
    try:
        plan = Plan(user.plan)
    except ValueError:
        # Unknown plan string — treat as Free (safest default).
        plan = Plan.FREE
    limit_value = PLAN_LIMITS[plan][Resource.HISTORY]
    # Resource.HISTORY is an int (0/30/90); cast defensively.
    return int(limit_value) if isinstance(limit_value, int) else 0


def _clamp_limit(limit: int) -> int:
    """Clamp requested page size to [1, MAX_ALERTS_PAGE_SIZE]."""
    return max(1, min(limit, MAX_ALERTS_PAGE_SIZE))


def _encode_cursor(first_seen: datetime, alert_id: int) -> str:
    """Encode keyset position as an opaque base64url cursor string.

    Payload: JSON array [first_seen_iso_utc, id].
    Uses URL-safe base64 without padding for clean query-string transport.
    """
    # Normalise to UTC so round-trip is timezone-consistent.
    fs_utc = first_seen.astimezone(UTC) if first_seen.tzinfo else first_seen.replace(tzinfo=UTC)
    payload = json.dumps([fs_utc.isoformat(), alert_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()


def _decode_cursor(raw: str) -> tuple[datetime, int]:
    """Decode and validate an opaque cursor string.

    Returns (first_seen_utc, id).
    Raises InvalidCursorError on any malformed/tampered input.
    """
    try:
        # Re-add base64 padding (urlsafe_b64decode requires it).
        padded = raw + "=" * (-len(raw) % 4)
        decoded_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(decoded_bytes)
        if not (isinstance(payload, list) and len(payload) == 2):
            raise InvalidCursorError("cursor payload must be a 2-element array")
        fs_raw, id_raw = payload
        if not isinstance(fs_raw, str):
            raise InvalidCursorError("cursor first_seen must be a string")
        # `bool` is a subclass of `int` — reject it explicitly so `[iso, true]`
        # is not silently accepted as id=1.
        if not isinstance(id_raw, int) or isinstance(id_raw, bool):
            raise InvalidCursorError("cursor id must be an integer")
        if not (_MIN_CURSOR_ID <= id_raw <= _MAX_CURSOR_ID):
            raise InvalidCursorError("cursor id out of range")
        # Parse and normalise to UTC.
        fs = datetime.fromisoformat(fs_raw)
        if fs.tzinfo is None:
            raise InvalidCursorError("cursor first_seen must be timezone-aware")
        fs_utc = fs.astimezone(UTC)
        return fs_utc, int(id_raw)
    except InvalidCursorError:
        raise
    except Exception as exc:
        raise InvalidCursorError(f"cannot decode cursor: {exc}") from exc


def list_alerts(
    session: Session,
    *,
    user: User,
    limit: int = DEFAULT_ALERTS_PAGE_SIZE,
    cursor: str | None = None,
) -> AlertListResponse:
    """Return cursor-paginated alert list for the caller.

    History window: Free plan (0 days) → empty + history_unavailable=True.
    Pro/Team → filters alerts by first_seen within the window.
    All queries are tenant-scoped by user_id (CONVENTIONS, ADR-002).

    Keyset: ORDER BY first_seen DESC, id DESC.
    If cursor supplied, only rows strictly before (first_seen, id) cursor position
    are returned (stable pagination — no dupes/gaps on inserts).
    """
    history_days = _plan_history_days(user)
    history_unavailable = history_days == 0
    clamped_limit = _clamp_limit(limit)

    if history_unavailable:
        return AlertListResponse(
            items=[],
            next_cursor=None,
            history_unavailable=True,
        )

    cutoff: datetime = datetime.now(UTC) - timedelta(days=history_days)

    # Decode cursor position (raises InvalidCursorError if malformed → 422).
    cursor_pos: tuple[datetime, int] | None = None
    if cursor is not None:
        cursor_pos = _decode_cursor(cursor)

    # Keyset list query — tenant-scoped + history window + optional cursor filter.
    # Fetch clamped_limit + 1 to detect whether there is a next page.
    stmt = (
        select(Alert, Cluster.topic)
        .join(Cluster, Alert.cluster_id == Cluster.id)
        .where(Alert.user_id == user.id)
        .where(Cluster.user_id == user.id)
        .where(Alert.first_seen >= cutoff)
        .order_by(Alert.first_seen.desc(), Alert.id.desc())
        .limit(clamped_limit + 1)
    )

    if cursor_pos is not None:
        cursor_fs, cursor_id = cursor_pos
        # Row-value keyset predicate: (first_seen, id) < (cursor_fs, cursor_id).
        # literal() wraps Python values as SQLAlchemy column expressions (mypy-clean).
        stmt = stmt.where(
            tuple_(Alert.first_seen, Alert.id) < tuple_(literal(cursor_fs), literal(cursor_id))
        )

    rows = session.execute(stmt).all()

    # Determine next_cursor: if more rows exist than clamped_limit, there is a next page.
    has_next = len(rows) > clamped_limit
    page_rows = rows[:clamped_limit]

    next_cursor: str | None = None
    if has_next and page_rows:
        last_alert, _ = page_rows[-1]
        next_cursor = _encode_cursor(last_alert.first_seen, last_alert.id)

    items: list[AlertRead] = [
        AlertRead(
            id=alert.id,
            score=alert.score,
            topic=topic,
            first_seen=alert.first_seen,
            channels_count=alert.channels_count,
            delivery_status=alert.delivery_status,
        )
        for alert, topic in page_rows
    ]

    return AlertListResponse(
        items=items,
        next_cursor=next_cursor,
        history_unavailable=False,
    )


def get_alert(
    session: Session,
    *,
    user: User,
    alert_id: int,
) -> AlertRead | None:
    """Return one alert detail, or None if missing / other tenant's (-> 404).

    Tenant-scoped: filters by (id, user_id) so a foreign alert is indistinguishable
    from a missing one (no existence leak, ADR-002).
    """
    stmt = (
        select(Alert, Cluster.topic)
        .join(Cluster, Alert.cluster_id == Cluster.id)
        .where(Alert.id == alert_id)
        .where(Alert.user_id == user.id)
        .where(Cluster.user_id == user.id)
    )
    row = session.execute(stmt).one_or_none()
    if row is None:
        return None
    alert, topic = row
    return AlertRead(
        id=alert.id,
        score=alert.score,
        topic=topic,
        first_seen=alert.first_seen,
        channels_count=alert.channels_count,
        delivery_status=alert.delivery_status,
    )
