"""Shared mock Telegram client/pool fixtures for collector unit tests (no network)."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from types import SimpleNamespace

from collector.telegram.account_pool import AccountPool


class FakeFloodWaitError(Exception):
    """Mimics telethon FloodWaitError: carries a `.seconds` retry hint."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds


def make_message(msg_id: int, text: str = "hi") -> SimpleNamespace:
    """Build a stub Telethon message the pure mapper can read."""
    return SimpleNamespace(
        id=msg_id,
        message=text,
        views=100,
        forwards=5,
        reactions=SimpleNamespace(results=[SimpleNamespace(count=2)]),
        date=datetime(2026, 6, 8, tzinfo=UTC),
        post_author="Author",
        media=None,
    )


class FakeClient:
    """A mock Telethon client: records calls, yields messages, can raise on demand."""

    def __init__(
        self,
        *,
        messages: Sequence[SimpleNamespace] | None = None,
        raise_on_iter: Exception | None = None,
        raise_on_entity: Exception | None = None,
    ) -> None:
        self._messages = list(messages or [make_message(1)])
        self._raise_on_iter = raise_on_iter
        self._raise_on_entity = raise_on_entity
        self.connect_calls = 0
        self.iter_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def get_entity(self, handle: str) -> object:
        if self._raise_on_entity is not None:
            raise self._raise_on_entity
        return SimpleNamespace(handle=handle)

    async def iter_messages(
        self, entity: object, *, offset_date: datetime | None
    ) -> AsyncIterator[SimpleNamespace]:
        self.iter_calls += 1
        if self._raise_on_iter is not None:
            raise self._raise_on_iter
        for msg in self._messages:
            yield msg


def make_pool(clients: list[FakeClient]) -> AccountPool:
    """Build an AccountPool over given fake clients with a controllable clock."""
    factory_iter = iter(clients)

    def factory(_session: str) -> FakeClient:
        return next(factory_iter)

    sessions = [f"session-{i}" for i in range(len(clients))]
    return AccountPool.from_sessions(sessions=sessions, factory=factory)
