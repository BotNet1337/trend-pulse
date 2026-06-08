"""`DELETE /account` — GDPR self-service account erasure (task-011, overview §7).

Tenant-scoped by construction: the handler passes ONLY `current_user.id` to
`delete_user`, so an authenticated user can delete only themselves — never another
tenant's account. The single cascading DELETE (compliance.account) removes all
dependent rows via `ON DELETE CASCADE` (task-002). Returns 204 No Content.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.deps import current_user, get_tenant_user_id
from api.watchlist.deps import get_db_session
from compliance.account import delete_user
from storage.models.users import User

router = APIRouter(tags=["account"])


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    user: User = Depends(current_user),
    session: Session = Depends(get_db_session),
) -> None:
    """Delete the authenticated user and all their data (cascade) -> 204."""
    delete_user(session, get_tenant_user_id(user))
