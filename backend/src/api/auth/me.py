"""Read-only GET /users/me endpoint (TASK-014 C2).

Returns the current authenticated user's profile: email, plan, is_verified.
This is a thin additive read-route — no mutations (UserUpdate is out of scope for C2).

Design: own router + Pydantic response schema so the shape is explicit and
independent of the fastapi-users UserRead (which lacks `plan`). All data comes
directly from the `current_user` dependency (tenant-scoped), never from external
input.

mypy-strict: full type hints, no bare Any, no magic literals.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from api.auth.backend import current_user
from billing.plans import Plan
from storage.models.users import User

router = APIRouter(tags=["users"])


class UserMeResponse(BaseModel):
    """Public current-user payload (read-only, no secrets)."""

    id: int
    email: EmailStr
    plan: str
    is_verified: bool
    # TASK-063: client-side admin UX flag (NOT a security boundary — the real
    # gate is `current_superuser` on the ops routes, which returns 403).
    is_superuser: bool

    model_config = {"from_attributes": True}


@router.get("/users/me", response_model=UserMeResponse)
def get_users_me(user: User = Depends(current_user)) -> UserMeResponse:
    """Return the authenticated user's profile.

    Behind `current_user` dependency: returns 401 without a valid auth cookie.
    Tenant-scoped: only reads data belonging to the requesting user.
    """
    # Normalise plan to lowercase string; default to Plan.FREE if somehow missing.
    plan_value: str = user.plan if user.plan else Plan.FREE
    return UserMeResponse(
        id=user.id,
        email=user.email,
        plan=plan_value,
        is_verified=user.is_verified,
        is_superuser=user.is_superuser,
    )
