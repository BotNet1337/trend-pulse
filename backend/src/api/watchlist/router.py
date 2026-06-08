"""Watchlist CRUD router (tenant-scoped, behind `current_user`).

Handlers are sync `def` (the repos are sync; FastAPI runs them in a threadpool).
Domain errors map to HTTP at this boundary:
- RefValidationError      -> 422 (Pydantic already 422s malformed bodies)
- LimitExceededError      -> 402 (plan limit; full enforcement task-010)
- DuplicateWatchlistError -> 409 (unique (user_id, channel_id, topic))
- not found / other tenant-> 404 (no existence leak, ADR-002)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps import current_user, get_tenant_user_id
from api.watchlist import service
from api.watchlist.deps import get_db_session
from api.watchlist.exceptions import (
    DuplicateWatchlistError,
    LimitExceededError,
    RefValidationError,
)
from api.watchlist.schemas import WatchlistCreate, WatchlistRead, WatchlistUpdate
from storage.models.users import User

router = APIRouter(prefix="/watchlists", tags=["watchlist"])

_NOT_FOUND = "watchlist not found"


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WatchlistRead)
def create_watchlist(
    data: WatchlistCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> WatchlistRead:
    """Create one watchlist (single channel) for the caller -> 201 WatchlistRead."""
    try:
        return service.create(session, user=user, data=data)
    except RefValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LimitExceededError as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc
    except DuplicateWatchlistError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("", response_model=list[WatchlistRead])
def list_watchlists(
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> list[WatchlistRead]:
    """List only the caller's watchlists (tenant-scoped)."""
    return service.list_for_user(session, user_id=get_tenant_user_id(user))


@router.get("/{watchlist_id}", response_model=WatchlistRead)
def get_watchlist(
    watchlist_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> WatchlistRead:
    """Get one owned watchlist; missing / other tenant's id -> 404."""
    result = service.get(session, user_id=get_tenant_user_id(user), watchlist_id=watchlist_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return result


@router.patch("/{watchlist_id}", response_model=WatchlistRead)
def update_watchlist(
    watchlist_id: int,
    data: WatchlistUpdate,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> WatchlistRead:
    """Partial update of an owned watchlist; missing / other tenant's id -> 404."""
    user_id = get_tenant_user_id(user)
    try:
        result = service.update(session, user_id=user_id, watchlist_id=watchlist_id, data=data)
    except RefValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DuplicateWatchlistError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
    return result


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    watchlist_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> None:
    """Delete an owned watchlist; missing / other tenant's id -> 404."""
    deleted = service.delete(session, user_id=get_tenant_user_id(user), watchlist_id=watchlist_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NOT_FOUND)
