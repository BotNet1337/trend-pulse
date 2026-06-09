"""API-keys CRUD router — POST /api-keys (issue), GET /api-keys (list), DELETE (revoke).

Security model:
- POST is feature-gated: `assert_within_limit(session, user, Resource.API_ACCESS)`
  raises PlanLimitExceeded (→ 403) for Free/Pro; Team passes.  Reuses billing/limits.py.
- Plaintext is returned EXACTLY ONCE in ApiKeyCreated; subsequent reads use ApiKeyRead
  (no key/key_hash in list/detail). Tenant-scoped (only caller's keys).
- DELETE is soft-revoke (revoked_at set); unknown/foreign id → 404 (no existence leak).
- Behind `Depends(current_user)` only (cookie/JWT); API-key auth is NOT recursive
  (you can't use an API key to create/revoke API keys).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.api_keys import service
from api.api_keys.constants import MSG_API_KEY_NOT_FOUND
from api.api_keys.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from api.deps import current_user
from api.watchlist.deps import get_db_session
from billing.limits import assert_within_limit
from billing.plans import Resource
from storage.models.users import User

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreated)
def create_api_key(
    data: ApiKeyCreate,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> ApiKeyCreated:
    """Issue a new API key for the caller (Team plan only).

    Free/Pro → PlanLimitExceeded → 403 (via api/main.py exception handler).
    Plaintext key is returned ONCE in the response body and never stored in DB.
    """
    # Feature-gate: raises PlanLimitExceeded (mapped to 403) for Free/Pro.
    assert_within_limit(session, user, Resource.API_ACCESS)

    row, plaintext = service.create_api_key(session, user_id=user.id, name=data.name)

    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        key=plaintext,
        created_at=row.created_at,
    )


@router.get("", response_model=list[ApiKeyRead])
def list_api_keys(
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> list[ApiKeyRead]:
    """List all API keys for the caller (masked: prefix/name/timestamps, no key/key_hash)."""
    rows = service.list_api_keys(session, user_id=user.id)
    return [ApiKeyRead.model_validate(row) for row in rows]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> None:
    """Soft-revoke an API key owned by the caller.

    Unknown id or another tenant's id → 404 (no existence leak, ADR-002).
    The key_hash row is kept for audit; revoked_at marks it inactive.
    """
    revoked = service.revoke_api_key(session, user_id=user.id, key_id=key_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=MSG_API_KEY_NOT_FOUND,
        )
