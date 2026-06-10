"""Trending API router (TASK-039).

GET /trending?pack=<slug>&limit=<int>

Auth required (any plan — no plan gate, see Decision §Discussion). Returns
top-K viral clusters of the showcase tenant for the given pack within the last
24 hours, sorted by viral_score DESC. Response is aggregate-only (no raw content,
compliance §7).

Error cases:
  - 401 without valid session (fastapi-users current_user dependency).
  - 404 if the pack slug is not in the catalog.
  - 422 if limit > settings.trending_top_k_max.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.deps import current_user
from api.packs.data import get_pack
from api.trending import service
from api.trending.schemas import TrendingResponse
from api.watchlist.deps import get_db_session
from config import get_settings
from storage.models.users import User

router = APIRouter(prefix="/trending", tags=["trending"])

_PACK_NOT_FOUND = "pack not found"


@router.get("", response_model=TrendingResponse)
def get_trending(
    pack: str = Query(
        ...,
        description="Pack slug (e.g. 'crypto-ru'). Must be a known catalog slug.",
    ),
    limit: int = Query(
        default=None,
        ge=1,
        description=(
            "Max number of trending items to return. "
            "Defaults to settings.trending_top_k_default; max is settings.trending_top_k_max. "
            "Must be ≥ 1 (422 on non-positive values)."
        ),
    ),
    _user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> TrendingResponse:
    """Return the top trending clusters for a pack (showcase tenant, 24h window).

    No plan gate: Free users see /trending after registration (Decision §Discussion).
    This is showcase data (our own), not the user's personal history.

    pack:  Required. Pack slug from the catalog. 404 if unknown.
    limit: Optional. Must be ≤ settings.trending_top_k_max (422 otherwise).
           Defaults to settings.trending_top_k_default.

    Response includes warming_up=true when the showcase tenant is not yet warmed up
    (fresh deploy); the frontend should display «собираем сигналы…» in that case.
    """
    settings = get_settings()

    # Resolve limit with default fallback
    effective_limit = limit if limit is not None else settings.trending_top_k_default

    # Validate limit bound
    if effective_limit > settings.trending_top_k_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"limit must be ≤ {settings.trending_top_k_max}",
        )

    # Validate pack slug against catalog
    if get_pack(pack) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_PACK_NOT_FOUND)

    return service.get_trending(session, pack_slug=pack, limit=effective_limit)


__all__ = ["router"]
