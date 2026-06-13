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
    """A mock Telethon client: records calls, yields messages, can raise on demand.

    `iter_messages` models Telethon's REAL semantics (task-078/task-083) so the
    reader's window bound is actually exercised, not assumed. Verified against the
    installed `telethon/client/messages.py` (`_MessagesIter._init` /
    `_load_next_chunk`):
      * `messages` is the channel history in chronological order (oldest→newest);
      * `reverse=False` (Telethon default) yields newest→oldest and `offset_date`
        is the EXCLUSIVE UPPER bound ("messages *previous* to this date");
      * `reverse=True` yields oldest→newest and `offset_date` is the EXCLUSIVE
        LOWER bound — BUT when `offset_date` is None/falsy, `_init` sets
        `offset_id = 1`, so iteration starts at the channel's OLDEST message and
        walks forward (the task-083 prod trap: a flushed marker → ancient posts);
      * `limit` caps how many are yielded (whichever end the order starts from).
    `last_iter_kwargs` records what the reader actually passed at the seam.
    """

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
        self._connected = False
        self.last_iter_kwargs: dict[str, object] | None = None

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def get_entity(self, handle: str) -> object:
        if self._raise_on_entity is not None:
            raise self._raise_on_entity
        return SimpleNamespace(handle=handle)

    async def iter_messages(
        self,
        entity: object,
        *,
        offset_date: datetime | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[SimpleNamespace]:
        self.iter_calls += 1
        self.last_iter_kwargs = {
            "offset_date": offset_date,
            "reverse": reverse,
            "limit": limit,
        }
        if self._raise_on_iter is not None:
            raise self._raise_on_iter

        if reverse:
            # reverse=True → oldest→newest. Telethon's `_init` only honours
            # `offset_date` as a lower bound when it is truthy; with no
            # `offset_date` it forces `offset_id = 1`, i.e. start at the channel's
            # OLDEST message and walk forward (the task-083 flushed-marker trap).
            ordered = self._messages
            lower_bound = offset_date

            def keep(msg: SimpleNamespace) -> bool:
                if lower_bound is None or msg.date is None:
                    return True
                return msg.date > lower_bound  # exclusive lower bound

        else:
            # reverse=False (Telethon default) → newest→oldest. `offset_date` is
            # the EXCLUSIVE UPPER bound ("messages *previous* to this date").
            ordered = list(reversed(self._messages))
            upper_bound = offset_date

            def keep(msg: SimpleNamespace) -> bool:
                if upper_bound is None or msg.date is None:
                    return True
                return msg.date < upper_bound  # exclusive upper bound

        yielded = 0
        for msg in ordered:
            if not keep(msg):
                continue
            if limit is not None and yielded >= limit:
                return
            yielded += 1
            yield msg


def make_pool(clients: list[FakeClient]) -> AccountPool:
    """Build an AccountPool over given fake clients with a controllable clock."""
    factory_iter = iter(clients)

    def factory(_session: str) -> FakeClient:
        return next(factory_iter)

    sessions = [f"session-{i}" for i in range(len(clients))]
    return AccountPool.from_sessions(sessions=sessions, factory=factory)
