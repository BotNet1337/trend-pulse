"""AC4 — FLOOD_WAIT -> backoff + rotation; all-flood -> AllAccountsFloodWaitError."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from types import SimpleNamespace

import pytest

from collector.base import SourceKind, SourceRef
from collector.constants import FLOOD_WAIT_INLINE_CAP_SECONDS, POOL_MAX, POOL_MIN
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

    # TASK-131: "@ch" → slot 0 for n=1,2,3 (sha256 % healthy_count), so the flooding
    # account at index 0 is acquired first — preserving the flood→rotate→healthy intent.
    posts = [p async for p in collector.read([SourceRef(SourceKind.TELEGRAM, "@ch")], since=None)]

    assert len(posts) == 1
    assert posts[0].external_id == "7"
    # Backoff was applied (slept for the flood-wait hint).
    assert 1 in slept
    # Rotation happened: the healthy (second) client served the read.
    assert healthy.iter_calls == 1


# ---------------------------------------------------------------------------
# Prod hang regression (pool=1): a FLOOD_WAIT above the inline cap must abort
# the ref (AllAccountsFloodWaitError -> collect_tick skips it with a warning)
# instead of parking the coroutine on `await sleep(<server hint>)` for the
# task's lifetime ("User is already connected!" then silence, celery slot held).
# ---------------------------------------------------------------------------


class _Clock2:
    """Manually advanced monotonic clock shared by the pool and fake sleep."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _pool_of(clients: list[FakeClient], clock: _Clock2) -> AccountPool:
    pool = make_pool(clients)
    pool._now = clock
    return pool


def _clock_sleep(clock: _Clock2, slept: list[float]) -> Callable[[float], Awaitable[None]]:
    async def _sleep(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds)

    return _sleep


class _FloodOnceClient(FakeClient):
    """FakeClient that floods exactly once on iter, then yields its messages."""

    def __init__(self, wait_seconds: int) -> None:
        super().__init__(messages=[make_message(5)])
        self._flood: Exception | None = FakeFloodWaitError(wait_seconds)

    async def iter_messages(
        self,
        entity: object,
        *,
        offset_date: datetime | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[SimpleNamespace]:
        self.iter_calls += 1
        if self._flood is not None:
            error, self._flood = self._flood, None
            raise error
        for msg in self._messages:
            yield msg


# TASK-131: deterministic sharding acquires the mapped slot first; "@ch" → slot 0 for
# n=1,2,3, so the account at index 0 (flooding/under-test) is acquired first as before.
_REF = SourceRef(SourceKind.TELEGRAM, "@ch")


@pytest.mark.asyncio
async def test_pool1_long_flood_aborts_ref_instead_of_sleeping() -> None:
    # Pool of ONE account: "rotation" lands on the same cooling account. A wait
    # above the inline cap must surface AllAccountsFloodWaitError (ref skipped),
    # never an in-task sleep of the full server hint.
    clock = _Clock2()
    long_wait = FLOOD_WAIT_INLINE_CAP_SECONDS + 1
    client = FakeClient(raise_on_iter=FakeFloodWaitError(long_wait))
    pool = _pool_of([client], clock)
    slept: list[float] = []
    collector = TelegramCollector(pool, sleep=_clock_sleep(clock, slept))

    with pytest.raises(AllAccountsFloodWaitError):
        _ = [post async for post in collector.read([_REF], since=None)]

    # The long server hint was never slept inside the task.
    assert all(seconds < long_wait for seconds in slept)


@pytest.mark.asyncio
async def test_pool1_short_flood_retries_without_reconnecting() -> None:
    # A short hint (<= cap) still waits it out and finishes the read — but the
    # already-connected client must NOT be reconnected ("User is already
    # connected!" noise on the prod hang path).
    clock = _Clock2()
    client = _FloodOnceClient(3)
    pool = _pool_of([client], clock)
    slept: list[float] = []
    collector = TelegramCollector(pool, sleep=_clock_sleep(clock, slept))

    posts = [post async for post in collector.read([_REF], since=None)]

    assert [post.external_id for post in posts] == ["5"]
    assert 3 in slept
    assert client.connect_calls == 1


@pytest.mark.asyncio
async def test_long_flood_rotates_to_ready_account_without_sleeping_hint() -> None:
    # Pool > 1: a long flood on one account rotates to a READY account
    # immediately instead of sleeping the flooded account's full hint.
    clock = _Clock2()
    long_wait = FLOOD_WAIT_INLINE_CAP_SECONDS + 540
    flooding = FakeClient(raise_on_iter=FakeFloodWaitError(long_wait))
    healthy = FakeClient(messages=[make_message(7)])
    pool = _pool_of([flooding, healthy], clock)
    slept: list[float] = []
    collector = TelegramCollector(pool, sleep=_clock_sleep(clock, slept))

    posts = [post async for post in collector.read([_REF], since=None)]

    assert [post.external_id for post in posts] == ["7"]
    assert healthy.iter_calls == 1
    assert all(seconds < long_wait for seconds in slept)


async def test_pool_exhausted_emits_repeating_ops_alert_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TASK-101: a fully dead/quarantined pool fires a (throttled, repeating)
    `pool_exhausted` ops alert and re-raises PoolExhaustedError (ref still skipped)."""
    from unittest.mock import MagicMock

    import observability.pool_health as ph
    from collector.errors import PoolExhaustedError

    pool = make_pool([FakeClient()])
    pool.acquire()
    pool.quarantine_current()  # 1/1 dead -> next acquire() raises PoolExhaustedError

    async def _noop_sleep(_seconds: float) -> None:
        return None

    settings = SimpleNamespace(pool_min_healthy=3)
    collector = TelegramCollector(pool, settings=settings, redis=MagicMock(), sleep=_noop_sleep)

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(ph, "notify_ops", lambda **kw: calls.append(kw))

    ref = SourceRef(kind=SourceKind.TELEGRAM, handle="@x")
    with pytest.raises(PoolExhaustedError):
        async for _ in collector.read([ref], None):
            pass

    reasons = [c.get("reason") for c in calls]
    assert "pool_exhausted" in reasons


# ---------------------------------------------------------------------------
# TASK-115 — per-account health snapshot view + last_error_reason
# ---------------------------------------------------------------------------


def test_account_statuses_reports_healthy_cooling_quarantined() -> None:
    """1 healthy, 1 cooling (cooldown_until>now), 1 quarantined → correct AccountStatus.

    Cooldown seconds are present ONLY for the cooling account; index is the stable
    pool position; the recorded last_error_reason is surfaced (TASK-115 AC1).
    """
    from collector.telegram.account_pool import AccountStatus

    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # index 0 stays healthy.
    # index 1 → cooling: acquire it (rotate to it first), record reason, flood-wait it.
    pool.acquire()  # current = 0
    pool.report_flood_wait(retry_after_seconds=10)  # 0 cooling, rotate → current = 1
    # Make index 0 healthy again by advancing past its cooldown, but keep index 1/2 work.
    # Simpler: build explicit states directly on the dataclasses (no behaviour change).
    pool._accounts[0].cooldown_until = 0.0  # healthy
    pool._accounts[0].last_error_reason = ""
    pool._accounts[1].cooldown_until = clock.t + 30.0  # cooling
    pool._accounts[1].last_error_reason = "FLOOD_WAIT"
    pool._accounts[2].quarantined = True
    pool._accounts[2].last_error_reason = "AuthKeyDuplicatedError"

    statuses = pool.account_statuses()
    assert len(statuses) == 3
    assert all(isinstance(s, AccountStatus) for s in statuses)

    by_index = {s.index: s for s in statuses}
    assert by_index[0].state == "healthy"
    assert by_index[0].cooldown_remaining_seconds is None

    assert by_index[1].state == "cooling"
    assert by_index[1].cooldown_remaining_seconds == pytest.approx(30.0)
    assert by_index[1].last_error_reason == "FLOOD_WAIT"

    assert by_index[2].state == "quarantined"
    assert by_index[2].cooldown_remaining_seconds is None
    assert by_index[2].last_error_reason == "AuthKeyDuplicatedError"


def test_account_statuses_empty_pool_is_empty_list() -> None:
    from collector.telegram.account_pool import AccountPool

    pool = AccountPool()
    assert pool.account_statuses() == []


def test_account_statuses_is_immutable() -> None:
    """AccountStatus is frozen — callers cannot mutate the snapshot view."""
    import dataclasses

    pool = make_pool([FakeClient()])
    status = pool.account_statuses()[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        status.state = "cooling"  # type: ignore[misc]


def test_note_current_error_sets_reason_on_current_account() -> None:
    pool = make_pool([FakeClient(), FakeClient()])
    pool.acquire()  # current = 0
    pool.note_current_error("FLOOD_WAIT")
    assert pool.account_statuses()[0].last_error_reason == "FLOOD_WAIT"
    assert pool.account_statuses()[1].last_error_reason == ""


def test_note_current_error_empty_pool_is_noop() -> None:
    from collector.telegram.account_pool import AccountPool

    pool = AccountPool()
    pool.note_current_error("FLOOD_WAIT")  # must not raise
    assert pool.account_statuses() == []
