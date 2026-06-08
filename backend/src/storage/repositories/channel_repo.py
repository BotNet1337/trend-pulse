"""GLOBAL repository for `channels` — NO `user_id` (ADR-001/002).

Channels are shared across tenants and deduped by `(source_kind, handle)`.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models.channels import Channel, SourceKind
from storage.repositories.base import Repository


class ChannelRepository(Repository[Channel]):
    model = Channel

    def get_or_create(self, session: Session, *, source_kind: SourceKind, handle: str) -> Channel:
        stmt = (
            select(Channel)
            .where(Channel.source_kind == source_kind)
            .where(Channel.handle == handle)
        )
        existing = session.scalars(stmt).one_or_none()
        if existing is not None:
            return existing
        channel = Channel(source_kind=source_kind, handle=handle)
        session.add(channel)
        session.flush()
        return channel
