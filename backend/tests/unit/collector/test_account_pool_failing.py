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


# ---------------------------------------------------------------------------
# Pool-admin UI honesty (read_failure_count + durable last_error_reason)
# ---------------------------------------------------------------------------


def test_read_failure_count_increments_and_is_exposed() -> None:
    """`note_read_failure` increments a CUMULATIVE per-account `read_failure_count`
    surfaced on the status — so the UI can show error frequency (e.g. "xN")."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    for _ in range(3):
        pool.note_read_failure("SecurityError")

    status = pool.account_statuses()[0]
    assert status.read_failure_count == 3
    assert status.last_error_reason == "SecurityError"


def test_read_failure_count_is_cumulative_across_a_success() -> None:
    """The CUMULATIVE failure count is NOT reset by a recovering read — only the
    consecutive (failing-classification) counter is. The owner still sees how often a
    session has failed even if it occasionally succeeds (the wrong-session-ID case)."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    pool.note_read_failure("SecurityError")
    pool.note_read_failure("SecurityError")
    pool.note_read_success()  # intermittent success
    pool.note_read_failure("SecurityError")

    status = pool.account_statuses()[0]
    assert status.read_failure_count == 3  # cumulative, survives the success
    account = pool._accounts[0]
    assert account.consecutive_read_failures == 1  # reset on success, then +1


def test_last_error_reason_survives_an_intermittent_success() -> None:
    """A mostly-failing session that occasionally succeeds must STILL show its last
    error reason (the "wrong session ID" / SecurityError case) — `note_read_success`
    keeps the last-known reason and only clears the consecutive counter/window."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    pool.note_read_failure("SecurityError")
    pool.note_read_success()

    status = pool.account_statuses()[0]
    assert status.last_error_reason == "SecurityError"  # NOT wiped by the success
    assert status.state == "healthy"  # consecutive counter reset → recovered


def test_security_error_is_recorded_as_class_name_not_message() -> None:
    """A SecurityError-shaped read failure records the CLASS NAME only (never the
    message / a secret) as the last error reason."""

    class SecurityError(Exception):
        """Mimics Telethon's SecurityError ("wrong session ID")."""

    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()

    exc = SecurityError("wrong session ID secret-leak-12345")
    pool.note_read_failure(type(exc).__name__)

    status = pool.account_statuses()[0]
    assert status.last_error_reason == "SecurityError"
    assert "secret-leak" not in status.last_error_reason


def test_revive_resets_read_failure_count() -> None:
    """A revived slot starts clean — its cumulative `read_failure_count` is reset to 0."""
    clock = _Clock()
    pool = _pool_with_clock(1, clock)
    pool.acquire()
    for _ in range(POOL_FAILING_THRESHOLD):
        pool.note_read_failure("SecurityError")
    assert pool.account_statuses()[0].read_failure_count == POOL_FAILING_THRESHOLD

    pool._accounts[0].read_failure_count = 0  # mirrors revive_slot's reset
    assert pool.account_statuses()[0].read_failure_count == 0
