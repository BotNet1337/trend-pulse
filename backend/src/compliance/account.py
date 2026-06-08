"""GDPR account deletion (task-011, overview §7) — the single delete path.

`delete_user` issues ONE `DELETE FROM users WHERE id = :id` (bind param) and relies
entirely on the schema's `ON DELETE CASCADE` on every user-owned FK (task-002,
ADR-002) to remove all dependent rows (watchlists, clusters, scores, alerts,
posts, subscriptions, oauth_accounts). It deliberately does NOT enumerate child
tables — duplicating the cascade by hand would drift from the schema; the
no-orphan guarantee is proven by the integration test.

Both the `DELETE /account` endpoint and any operator CLI call this one function so
the deletion logic has a single source of truth (no drift). Tenant scoping is the
caller's responsibility: the endpoint passes only `current_user.id`, so a user can
only ever delete themselves.
"""

from typing import cast

from sqlalchemy import CursorResult, delete
from sqlalchemy.orm import Session

from storage.models.users import User


def delete_user(session: Session, user_id: int) -> int:
    """Delete the user row by id; cascades remove all dependent rows. Returns count.

    A single set-based DELETE with a bind param (CONVENTIONS: never f-string SQL).
    Returns the number of `users` rows deleted (1 normally, 0 if absent — callers
    decide whether a missing user is an error). The caller owns the transaction.
    """
    result = cast(CursorResult[object], session.execute(delete(User).where(User.id == user_id)))
    return result.rowcount
