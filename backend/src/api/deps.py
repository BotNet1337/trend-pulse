"""Shared FastAPI dependencies for user-facing routes.

Re-exports `current_user` (the fastapi-users active-user dependency) so other
routers depend on `api.deps` rather than reaching into `api.auth` internals
(CONVENTIONS: cross-module via public surface). `get_tenant_user_id` is the single
place that derives the tenant scope key from the authenticated user (ADR-002:
scope by token-derived `user_id`, never request body).
"""

from api.auth import current_user
from storage.models.users import User

__all__ = ["current_user", "get_tenant_user_id"]


def get_tenant_user_id(user: User) -> int:
    """Return the tenant scope key for an authenticated user (their integer id)."""
    return user.id
