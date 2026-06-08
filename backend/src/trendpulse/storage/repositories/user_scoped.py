"""Base for tenant-isolated repositories (ADR-002).

Every read REQUIRES a `user_id` and filters `WHERE model.user_id == user_id`.
There is deliberately NO method that lists user data without a `user_id` — this
base does not inherit the global `Repository.list`, so no such overload exists.

`ModelT` is bound to `UserOwnedMixin`, so `model.id`/`model.user_id` are statically
typed `Mapped[int]` columns (no bare `Any`, no `# type: ignore`).
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from trendpulse.storage.models.base import UserOwnedBase


class UserScopedRepository[ModelT: UserOwnedBase]:
    """CRUD constrained to a single tenant; `user_id` is always mandatory."""

    model: type[ModelT]

    def get_by_id(self, session: Session, *, user_id: int, entity_id: int) -> ModelT | None:
        stmt = (
            select(self.model)
            .where(self.model.id == entity_id)
            .where(self.model.user_id == user_id)
        )
        return session.scalars(stmt).one_or_none()

    def list(self, session: Session, *, user_id: int) -> Sequence[ModelT]:
        stmt = select(self.model).where(self.model.user_id == user_id)
        return session.scalars(stmt).all()

    def create(self, session: Session, entity: ModelT) -> ModelT:
        session.add(entity)
        session.flush()
        return entity

    def delete(self, session: Session, *, user_id: int, entity: ModelT) -> None:
        if entity.user_id != user_id:
            raise ValueError("entity does not belong to the given user_id")
        session.delete(entity)
        session.flush()
