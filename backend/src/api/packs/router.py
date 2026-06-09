"""Packs API router (TASK-038).

Routes:
  GET  /packs                      — catalog list (auth required)
  POST /packs/{slug}/subscribe     — subscribe to a pack (1-click)
  DELETE /packs/{slug}/subscribe   — unsubscribe from a pack

All routes require authentication via `current_user` (cookie/JWT). Mutations are
intentionally cookie-only (same surface policy as watchlist mutations). Error
mapping follows the existing convention:
  - PlanLimitExceeded(402) → handled globally by app exception handler
  - unknown slug → 404
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import current_user, get_tenant_user_id
from api.packs import service
from api.packs.data import get_pack, list_packs
from api.packs.schemas import PackRead, SubscribeResult, UnsubscribeResult
from api.watchlist.deps import get_db_session
from storage.models.users import User

router = APIRouter(prefix="/packs", tags=["packs"])

_SLUG_NOT_FOUND = "pack not found"


@router.get("", response_model=list[PackRead])
def get_packs(
    _user: User = Depends(current_user),
) -> list[PackRead]:
    """Return the full curated pack catalog (auth required — AC1).

    No DB query: the catalog is a static in-memory structure. Auth is required
    so unauthenticated crawlers cannot enumerate the catalog.
    """
    return [
        PackRead(
            slug=p.slug,
            title=p.title,
            topic=p.topic,
            channels_count=len(p.channels),
        )
        for p in list_packs()
    ]


@router.post("/{slug}/subscribe", response_model=SubscribeResult)
def subscribe_pack(
    slug: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> SubscribeResult:
    """Subscribe to a curated pack — creates watchlist rows with pack_slug marker.

    - 404 if slug not in catalog.
    - 402 if the user has reached their PACKS plan limit (handled globally).
    - Idempotent: re-subscribing the same pack returns created=0, not an error.
    - Skip-conflicts (channel already watched manually) are counted in `skipped`.
    """
    pack = get_pack(slug)
    if pack is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SLUG_NOT_FOUND)

    return service.subscribe(session, user=user, pack=pack)


@router.delete("/{slug}/subscribe", response_model=UnsubscribeResult)
def unsubscribe_pack(
    slug: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> UnsubscribeResult:
    """Unsubscribe from a pack — deletes all watchlist rows with this pack_slug.

    - 404 if slug not in catalog (unknown pack — not just "not subscribed").
    - 200 with deleted=0 if the slug is valid but the user is not subscribed.
    - Manual watchlists (pack_slug IS NULL) are NEVER touched.
    """
    if get_pack(slug) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _SLUG_NOT_FOUND)

    return service.unsubscribe(
        session,
        user_id=get_tenant_user_id(user),
        pack_slug=slug,
    )


__all__ = ["router"]
