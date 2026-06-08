"""Generic CRUD repository base operating on a provided `Session`.

Sessions are passed in (unit-of-work owned by the caller / `get_session`); the
repository never opens or commits its own session.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from trendpulse.storage.models.base import Base


class Repository[ModelT: Base]:
    """CRUD over a single mapped model. Subclasses set `model`."""

    model: type[ModelT]

    def get_by_id(self, session: Session, entity_id: int) -> ModelT | None:
        return session.get(self.model, entity_id)

    def list(self, session: Session) -> Sequence[ModelT]:
        return session.scalars(select(self.model)).all()

    def create(self, session: Session, entity: ModelT) -> ModelT:
        session.add(entity)
        session.flush()
        return entity

    def delete(self, session: Session, entity: ModelT) -> None:
        session.delete(entity)
        session.flush()
