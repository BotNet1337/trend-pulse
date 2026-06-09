"""Alerts read service — tenant-scoped, read-only (TASK-016 C4, CONVENTIONS).

Reads alerts via AlertRepository (cross-module via public interface per CONVENTIONS),
joins Cluster for `topic`, applies history window from PLAN_LIMITS (billing seam),
and returns paginated AlertListResponse.

Named constants (no magic literals):
- DEFAULT_ALERTS_PAGE_SIZE: default page size when `limit` not supplied.
- MAX_ALERTS_PAGE_SIZE: hard cap — requests above this are silently clamped.

History window comes exclusively from `PLAN_LIMITS[plan][Resource.HISTORY]` (days):
- Free (0 days) → returns empty list + history_unavailable=True.
- Pro (30 days) / Team (90 days) → filters by first_seen >= now - window.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.alerts.schemas import AlertListResponse, AlertRead
from billing.plans import PLAN_LIMITS, Plan, Resource
from storage.models.alerts import Alert
from storage.models.clusters import Cluster
from storage.models.users import User

# Pagination constants (no magic literals, CONVENTIONS).
DEFAULT_ALERTS_PAGE_SIZE: int = 20
MAX_ALERTS_PAGE_SIZE: int = 100


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


def list_alerts(
    session: Session,
    *,
    user: User,
    limit: int = DEFAULT_ALERTS_PAGE_SIZE,
    offset: int = 0,
) -> AlertListResponse:
    """Return paginated alert list for the caller.

    History window: Free plan (0 days) → empty + history_unavailable=True.
    Pro/Team → filters alerts by first_seen within the window.
    All queries are tenant-scoped by user_id (CONVENTIONS, ADR-002).
    """
    history_days = _plan_history_days(user)
    history_unavailable = history_days == 0
    clamped_limit = _clamp_limit(limit)

    if history_unavailable:
        return AlertListResponse(
            items=[],
            total=0,
            limit=clamped_limit,
            offset=offset,
            history_unavailable=True,
        )

    cutoff: datetime = datetime.now(UTC) - timedelta(days=history_days)

    # Count query — tenant-scoped + history window.
    count_stmt = (
        select(func.count())
        .select_from(Alert)
        .where(Alert.user_id == user.id)
        .where(Alert.first_seen >= cutoff)
    )
    total: int = session.scalar(count_stmt) or 0

    # List query — join Cluster for topic, ordered newest-first.
    list_stmt = (
        select(Alert, Cluster.topic)
        .join(Cluster, Alert.cluster_id == Cluster.id)
        .where(Alert.user_id == user.id)
        .where(Alert.first_seen >= cutoff)
        .order_by(Alert.first_seen.desc())
        .limit(clamped_limit)
        .offset(offset)
    )
    rows = session.execute(list_stmt).all()

    items: list[AlertRead] = [
        AlertRead(
            id=alert.id,
            score=alert.score,
            topic=topic,
            first_seen=alert.first_seen,
            channels_count=alert.channels_count,
            delivery_status=alert.delivery_status,
        )
        for alert, topic in rows
    ]

    return AlertListResponse(
        items=items,
        total=total,
        limit=clamped_limit,
        offset=offset,
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
