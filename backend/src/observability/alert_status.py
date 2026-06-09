"""Aggregate alerts-by-status observability signal (task-023, AC4).

`emit_alerts_by_status` counts alert rows grouped by `delivery_status`
(pending / delivered / failed) and emits the counts via `log_event` —
an aggregate-only structured log suitable for alerting on a growing
pending backlog. Always returns zero-counts for absent statuses so the
caller gets a complete `{pending, delivered, failed}` snapshot.

Import note: this module imports `storage.models.alerts` (ORM model), but
NOT `celery_app` or `alerts.tasks`, so it is safe to import from any context
(beat worker, API, tests) without triggering a circular dependency.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from observability.logging import log_event
from storage.models.alerts import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
    Alert,
)

# All known delivery statuses — ensures zero-counts are reported even when
# a category has no rows (so dashboards/alerts don't mistake "absent" for "ok").
_ALL_STATUSES = (DELIVERY_STATUS_PENDING, DELIVERY_STATUS_DELIVERED, DELIVERY_STATUS_FAILED)


def emit_alerts_by_status(session: Session) -> dict[str, int]:
    """Count alerts by delivery_status, log them, and return the counts dict.

    Args:
        session: An open SQLAlchemy `Session` (caller provides/manages it).

    Returns:
        A dict with keys ``pending``, ``delivered``, ``failed`` (always present,
        zero-filled for absent statuses).
    """
    rows = session.execute(
        select(Alert.delivery_status, func.count(Alert.id)).group_by(Alert.delivery_status)
    ).all()

    # Build a complete counts snapshot — zero for any status with no rows.
    counts: dict[str, int] = {status: 0 for status in _ALL_STATUSES}
    for status, count in rows:
        if status in counts:
            counts[status] = count

    log_event(
        "alerts_by_status",
        pending=counts[DELIVERY_STATUS_PENDING],
        delivered=counts[DELIVERY_STATUS_DELIVERED],
        failed=counts[DELIVERY_STATUS_FAILED],
    )
    return counts
