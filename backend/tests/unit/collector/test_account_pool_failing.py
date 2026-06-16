"""TASK-118 — per-account read-outcome + the `failing` state (pool-health honesty).

A pool account can CONNECT yet have every READ raise a non-permanent transient error
(the swallowed "wrong session ID" class). Before TASK-118 such an account stayed
`healthy` forever. These tests pin the read-outcome bookkeeping and the new `failing`
classification — which is OBSERVATIONAL ONLY (it must NOT change `acquire()`).
"""

from __future__ import annotations

from collector.constants import (
    POOL_FAILING_NO_READ_WINDOW_SECONDS,
    POOL_FAILING_THRESHOLD,
)
from collector.telegram.account_pool import AccountPool

from .conftest import FakeClient, make_pool


class _Clock:
    """Manually advanced monotonic clock for deterministic window tests."""

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


def test_clean_read_stamps_success_and_resets_failures() -> None:
    """A clean read: `note_read_success` resets failures, stamps `last_read_ok_at`,
    and the account reports `healthy`."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    pool.note_read_failure("WrongSessionIdError")
    pool.note_read_success()

    statuses = pool.account_statuses()
    assert statuses[0].state == "healthy"
    account = pool._accounts[0]
    assert account.consecutive_read_failures == 0
    assert account.last_read_ok_at is not None


def test_failing_after_threshold_consecutive_failures() -> None:
    """After `POOL_FAILING_THRESHOLD` consecutive read failures a LIVE account is
    `failing` and carries the recorded reason."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("WrongSessionIdError")

    status = pool.account_statuses()[0]
    assert status.state == "failing"
    assert status.last_error_reason == "WrongSessionIdError"


def test_below_threshold_stays_healthy() -> None:
    """One read failure below the threshold (and a recent boot) is NOT yet failing."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    pool.note_read_failure("WrongSessionIdError")

    assert pool.account_statuses()[0].state == "healthy"


def test_success_resets_so_state_recovers() -> None:
    """A single clean read resets the failure counter so the state returns to healthy."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("WrongSessionIdError")
    assert pool.account_statuses()[0].state == "failing"

    pool.note_read_success()
    assert pool.account_statuses()[0].state == "healthy"


def test_failing_after_no_read_window_with_errors() -> None:
    """A live account that has errored at least once but NEVER read OK becomes
    `failing` once the no-read window elapses (even below the count threshold)."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    pool.note_read_failure("WrongSessionIdError")  # one failure → stamps the window start
    assert pool.account_statuses()[0].state == "healthy"

    clock.advance(POOL_FAILING_NO_READ_WINDOW_SECONDS + 1)
    assert pool.account_statuses()[0].state == "failing"


def test_no_read_window_does_not_fire_without_errors() -> None:
    """A freshly booted, never-read, never-errored account is NOT failing even after
    the window elapses (no errors present → nothing to alarm on)."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)

    clock.advance(POOL_FAILING_NO_READ_WINDOW_SECONDS + 1)
    assert pool.account_statuses()[0].state == "healthy"


def test_quarantine_precedence_over_failing() -> None:
    """A quarantined account stays `quarantined` even with read failures recorded."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()
    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("WrongSessionIdError")
    pool.quarantine_current()

    assert pool.account_statuses()[0].state == "quarantined"


def test_cooling_precedence_over_failing() -> None:
    """A cooling (FLOOD_WAIT) account stays `cooling` even with read failures recorded.

    FLOOD_WAIT must NOT increment the failing counter — it is recorded separately via
    `report_flood_wait`, not `note_read_failure`."""
    clock = _Clock()
    pool = _pool_with_clock(2, clock)
    pool.acquire()
    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("WrongSessionIdError")
    pool.report_flood_wait(retry_after_seconds=300)

    # account 0 is now cooling; cooling precedence wins over failing.
    assert pool.account_statuses()[0].state == "cooling"


def test_failing_does_not_change_acquire() -> None:
    """`failing` is observational: a failing account is STILL handed out by acquire()."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    client = pool.acquire()
    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("WrongSessionIdError")
    assert pool.account_statuses()[0].state == "failing"

    # Same client handed out again — acquisition is byte-for-byte unchanged.
    assert pool.acquire() is client


def test_empty_pool_statuses_empty() -> None:
    """An empty pool returns no statuses (no accounts to classify)."""
    clock = _Clock()
    pool = AccountPool(_now=clock)
    assert pool.account_statuses() == []
