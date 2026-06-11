"""Auth package — thin configuration over fastapi-users (+ httpx-oauth Google).

Re-exports the building blocks other routers/modules depend on: the `current_user`
dependency, the `fastapi_users` instance, the auth backend, the user manager, the
Google OAuth client builder, and the boundary schemas.
"""

from api.auth.backend import (
    auth_backend,
    build_jwt_strategy,
    current_superuser,
    current_user,
    fastapi_users,
)
from api.auth.oauth import build_google_oauth_client
from api.auth.schemas import UserCreate, UserRead, UserUpdate
from api.auth.users import UserManager, get_user_manager

__all__ = [
    "UserCreate",
    "UserManager",
    "UserRead",
    "UserUpdate",
    "auth_backend",
    "build_google_oauth_client",
    "build_jwt_strategy",
    "current_superuser",
    "current_user",
    "fastapi_users",
    "get_user_manager",
]
