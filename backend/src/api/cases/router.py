"""Cases API router — GET /cases (TASK-045).

Public endpoint: no authentication required (landing page pulls it without auth).
Returns only operator-confirmed cases (mainstream_at IS NOT NULL), sorted by
lead-time DESC, capped at cases_top_n_max.

Rate-limiting: global SlowAPIMiddleware applies (same as the rest of the API).
No per-route override needed — the default 120/min budget is appropriate for
a public, read-only endpoint that a landing page will call infrequently.

Error cases:
  - 422 if top_n > settings.cases_top_n_max.
  - 200 [] (empty list) when no qualifying cases exist.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.cases import service
from api.cases.schemas import CasesResponse
from api.watchlist.deps import get_db_session
from config import get_settings

router = APIRouter(prefix="/cases", tags=["cases"])

_TOP_N_OVER_MAX = "top_n must be ≤ {max}"


@router.get("", response_model=CasesResponse)
def get_cases(
    top_n: int | None = Query(
        default=None,
        ge=1,
        description=(
            "Max number of cases to return. "
            "Defaults to settings.cases_top_n_max; max is settings.cases_top_n_max. "
            "Must be ≥ 1 (422 on non-positive). "
            "422 if top_n exceeds the configured maximum."
        ),
    ),
    session: Session = Depends(get_db_session),
) -> CasesResponse:
    """Return top proof-of-speed cases sorted by lead-time DESC.

    Public endpoint: no authentication required.

    Only cases where the operator has set ``mainstream_at`` are returned
    — cases without a mainstream timestamp are not yet proof-points.

    Query params:
        top_n: Max items to return.  Defaults to settings.cases_top_n_max.
               422 if top_n exceeds settings.cases_top_n_max.

    Response sorted by ``lead_time_seconds`` (= mainstream_at - first_seen) DESC.
    """
    settings = get_settings()
    effective_top_n = top_n if top_n is not None else settings.cases_top_n_max

    if effective_top_n > settings.cases_top_n_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_TOP_N_OVER_MAX.format(max=settings.cases_top_n_max),
        )

    return service.get_cases(session, top_n=effective_top_n)


__all__ = ["router"]
