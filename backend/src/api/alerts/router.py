"""Alerts read router — GET /alerts (list) + GET /alerts/{id} (detail).

Read-only, tenant-scoped, behind `current_user`. No mutations of any kind.
History window and pagination limits come from billing.plans / service constants
(no magic literals). Tenant-scope: only the caller's alerts are visible; a
foreign or missing id returns 404 with no existence leak (ADR-002).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.alerts import service
from api.alerts.schemas import AlertListResponse, AlertRead
from api.alerts.service import DEFAULT_ALERTS_PAGE_SIZE
from api.deps import current_user, get_tenant_user_id
from api.watchlist.deps import get_db_session
from storage.models.users import User

router = APIRouter(prefix="/alerts", tags=["alerts"])

_ALERT_NOT_FOUND = "alert not found"


@router.get("", response_model=AlertListResponse)
def list_alerts(
    limit: int = Query(
        default=DEFAULT_ALERTS_PAGE_SIZE,
        ge=1,
        description="Maximum number of alerts to return (server silently clamps to max).",
    ),
    offset: int = Query(default=0, ge=0, description="Number of alerts to skip."),
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> AlertListResponse:
    """List the caller's alerts with pagination and plan-based history window.

    Free plan → returns empty list + history_unavailable=True (not 403).
    Pro/Team → returns alerts within the plan's history window (30/90 days).
    Always tenant-scoped: only the caller's alerts are returned.
    """
    return service.list_alerts(session, user=user, limit=limit, offset=offset)


@router.get("/{alert_id}", response_model=AlertRead)
def get_alert(
    alert_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> AlertRead:
    """Get one alert detail. Foreign or missing alert → 404 (no existence leak)."""
    _ = get_tenant_user_id(user)  # ensure tenant context is exercised
    result = service.get_alert(session, user=user, alert_id=alert_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_ALERT_NOT_FOUND)
    return result
