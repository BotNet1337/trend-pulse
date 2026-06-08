"""AC4 — FLOOD_WAIT -> backoff + rotation; all-flood -> AllAccountsFloodWaitError."""

import pytest

from collector.constants import POOL_MAX, POOL_MIN
from collector.errors import AllAccountsFloodWaitError, PoolConfigError
from collector.telegram.account_pool import AccountPool
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, FakeFloodWaitError, make_message, make_pool


class _Clock:
    """Manually advanced monotonic clock for deterministic cooldown tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _pool_with_clock(n: int, clock: _Clock) -> AccountPool:
    pool = make_pool([FakeClient() for _ in range(n)])
    pool._now = clock
    return pool


def test_pool_size_below_min_fails_fast() -> None:
    with pytest.raises(PoolConfigError):
        make_pool([FakeClient() for _ in range(POOL_MIN - 1)])


def test_pool_size_above_max_fails_fast() -> None:
    with pytest.raises(PoolConfigError):
        make_pool([FakeClient() for _ in range(POOL_MAX + 1)])


def test_flood_wait_rotates_to_next_account() -> None:
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    first = pool.acquire()
    pool.report_flood_wait()  # first account cools down, rotate
    second = pool.acquire()

    assert first is not second


def test_all_accounts_flood_raises() -> None:
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    for _ in range(3):
        pool.acquire()
        pool.report_flood_wait()

    # All three cooling down -> cannot acquire.
    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire()


def test_account_recovers_after_cooldown_elapses() -> None:
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    for _ in range(3):
        pool.acquire()
        pool.report_flood_wait(retry_after_seconds=10)
    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire()

    clock.advance(11)
    # At least one account is ready again.
    assert pool.acquire() is not None


@pytest.mark.asyncio
async def test_aclose_disconnects_all_pool_clients() -> None:
    clients = [FakeClient(), FakeClient(), FakeClient()]
    pool = make_pool(clients)
    await pool.aclose()
    assert all(c.disconnect_calls == 1 for c in clients)


@pytest.mark.asyncio
async def test_collector_aexit_disconnects_pool() -> None:
    clients = [FakeClient(), FakeClient(), FakeClient()]
    collector = TelegramCollector(make_pool(clients))
    async with collector:
        pass
    assert all(c.disconnect_calls == 1 for c in clients)


@pytest.mark.asyncio
async def test_reader_rotates_on_flood_and_completes() -> None:
    # First account raises FloodWait on iter; second yields a message.
    flooding = FakeClient(raise_on_iter=FakeFloodWaitError(1))
    healthy = FakeClient(messages=[make_message(7)])
    pool = make_pool([flooding, healthy, FakeClient()])

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    collector = TelegramCollector(pool, sleep=fake_sleep)
    from collector.base import SourceKind, SourceRef

    posts = [p async for p in collector.read([SourceRef(SourceKind.TELEGRAM, "@news")], since=None)]

    assert len(posts) == 1
    assert posts[0].external_id == "7"
    # Backoff was applied (slept for the flood-wait hint).
    assert 1 in slept
    # Rotation happened: the healthy (second) client served the read.
    assert healthy.iter_calls == 1
