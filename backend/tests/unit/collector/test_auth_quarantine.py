"""TASK-087 — permanent-auth quarantine + once-only ops alert (ФАЗА 0).

AC1 — is_permanent_auth_error: True for permanent auth classes (and subclasses via
      MRO), False for flood-like / generic exceptions.
AC2 — AccountPool.quarantine_current: evicts current account forever; returns a
      stable int fingerprint; quarantined excluded from cooling/cooldown.
AC3 — all-quarantined → PoolExhaustedError (not AllAccountsFloodWaitError).
AC4 — reader quarantines the dead account on a permanent auth error (resolve AND
      iter) and skips the ref; a later read uses a different (live) account.
AC5 — exactly ONE ops alert per dead session even if Redis throttle key is evicted
      (quarantine is the durable dedup); no secret/session string in the text.
AC6 — emit_pool_health reflects quarantined in healthy/aggregates.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.base import SourceKind, SourceRef
from collector.errors import (
    AllAccountsFloodWaitError,
    PoolExhaustedError,
    SourceUnavailableError,
)
from collector.telegram.auth_errors import is_permanent_auth_error
from collector.telegram.reader import TelegramCollector

from .conftest import FakeClient, make_message, make_pool

# TASK-131: deterministic channel→slot sharding means the read path now acquires the
# slot `pick_slot_for_channel(handle, healthy)` maps to (sha256(handle) % healthy_count),
# not always index 0. These tests put the DEAD/erroring account at index 0 and assert it
# is acquired first, so the handle must map to slot 0. "@dead" → slot 0 for n=1,2,3
# (verified), preserving each test's dead→quarantine→rotate-to-healthy intent unchanged.
_REF = SourceRef(SourceKind.TELEGRAM, "@dead")


# ---------------------------------------------------------------------------
# Fakes mimicking telethon permanent-auth errors (matched by class name)
# ---------------------------------------------------------------------------


# These deliberately reuse the REAL telethon class names: the classifier matches
# structurally by class name across the MRO, so the simulation must carry the same
# names telethon raises in prod (no telethon import needed in unit context).
class AuthKeyDuplicatedError(Exception):
    """Mimics telethon AuthKeyDuplicatedError (matched structurally by name)."""


class SessionRevokedError(Exception):
    """Mimics telethon SessionRevokedError (permanent, dead session)."""


class UserDeactivatedError(Exception):
    """Mimics telethon UserDeactivatedError (permanent, account banned)."""


class _SubclassedDeadSession(AuthKeyDuplicatedError):
    """A subclass of a permanent error — must be caught via MRO (parent's name)."""


class UnauthorizedError(Exception):
    """Mimics telethon's BASE UnauthorizedError — DELIBERATELY transient: a bare
    401 must NOT trigger permanent eviction (fail-safe, see auth_errors.py)."""


def _settings() -> object:
    from config import Settings

    return Settings.model_construct(
        pool_min_healthy=3,
        ops_telegram_bot_token="test-token",
        ops_telegram_chat_id="12345",
        ops_alert_throttle_seconds=3600,
        telegram_api_base_url="https://api.telegram.org",
        alert_http_timeout_seconds=10,
        jwt_secret="test",
        oauth_state_secret="test",
        google_client_id="test",
        google_client_secret="test",
    )


# ---------------------------------------------------------------------------
# AC1 — classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        AuthKeyDuplicatedError("dup"),
        SessionRevokedError("revoked"),
        UserDeactivatedError("banned"),
        _SubclassedDeadSession("dup-subclass"),  # caught via MRO (parent's name)
    ],
)
def test_is_permanent_auth_error_true(exc: Exception) -> None:
    assert is_permanent_auth_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        Exception("generic"),
        ValueError("bad"),
        UnauthorizedError("bare 401"),  # fail-safe: bare 401 is transient, NOT evicted
        SimpleNamespace(seconds=30),  # flood-like (has .seconds) — not permanent
    ],
)
def test_is_permanent_auth_error_false(exc: object) -> None:
    # SimpleNamespace isn't a BaseException — guard the call accordingly.
    if isinstance(exc, BaseException):
        assert is_permanent_auth_error(exc) is False


# ---------------------------------------------------------------------------
# AC2 — quarantine evicts current account forever
# ---------------------------------------------------------------------------


def test_quarantine_current_evicts_and_returns_fingerprint() -> None:
    a, b, c = FakeClient(), FakeClient(), FakeClient()
    pool = make_pool([a, b, c])

    first = pool.acquire()  # index 0 → client a
    assert first is a
    fingerprint = pool.quarantine_current()
    assert isinstance(fingerprint, int)
    assert pool.quarantined_count == 1

    # `a` must never be handed out again across many acquires.
    for _ in range(10):
        assert pool.acquire() is not a


def test_quarantined_excluded_from_cooling_and_cooldown() -> None:
    a, b = FakeClient(), FakeClient()
    pool = make_pool([a, b])
    pool.acquire()  # current = a
    pool.quarantine_current()  # a quarantined
    # b is healthy → cooling_count counts only non-quarantined cooling (0).
    assert pool.cooling_count == 0
    assert pool.quarantined_count == 1
    # A ready (b) exists → cooldown_remaining is 0 (quarantined a is ignored).
    assert pool.cooldown_remaining() == 0.0


# ---------------------------------------------------------------------------
# AC3 — all-quarantined raises PoolExhaustedError
# ---------------------------------------------------------------------------


def test_all_quarantined_raises_pool_exhausted() -> None:
    a, b = FakeClient(), FakeClient()
    pool = make_pool([a, b])
    pool.acquire()
    pool.quarantine_current()
    pool.acquire()
    pool.quarantine_current()
    with pytest.raises(PoolExhaustedError):
        pool.acquire()


def test_mixed_cooling_still_raises_flood_not_exhausted() -> None:
    # One quarantined, one merely cooling → still AllAccountsFloodWaitError
    # (a cooling account may recover; only an all-quarantined pool is exhausted).
    a, b = FakeClient(), FakeClient()
    pool = make_pool([a, b])
    pool.acquire()  # current a
    pool.quarantine_current()  # a dead
    pool.acquire()  # current b
    pool.report_flood_wait(retry_after_seconds=300)  # b cooling
    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire()


# ---------------------------------------------------------------------------
# AC4 — reader quarantines the dead account and skips the ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_quarantines_on_permanent_auth_resolve_error() -> None:
    dead = FakeClient(raise_on_entity=AuthKeyDuplicatedError("dup"))
    healthy = FakeClient(messages=[make_message(7)])
    pool = make_pool([dead, healthy])

    collector = TelegramCollector(pool)

    # First read hits the dead account → quarantined + ref skipped.
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert pool.quarantined_count == 1

    # Second read must NOT reuse the dead client — the healthy one serves it.
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["7"]
    assert healthy.iter_calls == 1
    assert dead.iter_calls == 0


class _PermAuthOnIterClient(FakeClient):
    """Resolves fine, then raises a permanent auth error during iter_messages."""

    async def iter_messages(
        self,
        entity: object,
        *,
        offset_date: datetime | None = None,
        reverse: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[SimpleNamespace]:
        self.iter_calls += 1
        raise SessionRevokedError("revoked")
        yield  # pragma: no cover (makes this an async generator)


@pytest.mark.asyncio
async def test_reader_quarantines_on_permanent_auth_iter_error() -> None:
    dead = _PermAuthOnIterClient()
    healthy = FakeClient(messages=[make_message(9)])
    pool = make_pool([dead, healthy])
    collector = TelegramCollector(pool)

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert pool.quarantined_count == 1


@pytest.mark.asyncio
async def test_reader_transient_non_flood_error_does_not_quarantine() -> None:
    # A generic (transient) resolve error keeps the old behaviour: ref skipped,
    # NO quarantine (the account may recover next tick).
    flaky = FakeClient(raise_on_entity=ConnectionError("network blip"))
    pool = make_pool([flaky, FakeClient()])
    collector = TelegramCollector(pool)

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert pool.quarantined_count == 0


# ---------------------------------------------------------------------------
# AC5 — exactly one ops alert, dedup survives Redis eviction, no secrets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_session_alert_fires_once_even_if_redis_evicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dead = FakeClient(raise_on_entity=AuthKeyDuplicatedError("dup"))
    healthy = FakeClient(messages=[make_message(7)])
    pool = make_pool([dead, healthy])

    # Redis SET NX ALWAYS returns True → throttle key is treated as evicted every
    # time. The alert must STILL fire only once because the quarantined account is
    # never acquired again (quarantine, not Redis, is the durable dedup).
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    sent: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent.append({"url": url, "json": kwargs.get("json")})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    collector = TelegramCollector(pool, settings=_settings(), redis=mock_redis)

    # Run several ticks; only the first hits the dead account (then it's quarantined).
    for _ in range(3):
        with contextlib.suppress(SourceUnavailableError):
            _ = [p async for p in collector.read([_REF], since=None)]

    # Exactly one dead-session alert delivered.
    dead_alerts = [
        s for s in sent if "мертва" in str(s["json"]) or "dead" in str(s["json"]).lower()
    ]
    assert len(dead_alerts) == 1, f"expected 1 dead-session alert, got {len(dead_alerts)}"

    # No secret/session string leaked into the text.
    body = str(dead_alerts[0]["json"])
    assert "session-" not in body
    assert "test-token" not in body


# ---------------------------------------------------------------------------
# AC6 — emit_pool_health reflects quarantined
# ---------------------------------------------------------------------------


def test_emit_pool_health_counts_quarantined_as_unhealthy() -> None:
    a, b, c = FakeClient(), FakeClient(), FakeClient()
    pool = make_pool([a, b, c])
    pool.acquire()
    pool.quarantine_current()  # one dead

    from observability.pool_health import emit_pool_health

    result = emit_pool_health(pool, _settings())
    assert result["size"] == 3
    assert result["quarantined"] == 1
    assert result["healthy"] == 2  # size - cooling - quarantined


# ---------------------------------------------------------------------------
# TASK-115 — reader records last_error_reason at the existing catch sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reader_sets_last_error_reason_on_permanent_auth() -> None:
    """On a permanent auth error the quarantined account's last_error_reason is the
    error CLASS NAME (TASK-115 AC2)."""
    dead = FakeClient(raise_on_entity=AuthKeyDuplicatedError("dup"))
    healthy = FakeClient(messages=[make_message(7)])
    pool = make_pool([dead, healthy])
    collector = TelegramCollector(pool)

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]

    statuses = {s.index: s for s in pool.account_statuses()}
    assert statuses[0].state == "quarantined"
    assert statuses[0].last_error_reason == "AuthKeyDuplicatedError"


@pytest.mark.asyncio
async def test_reader_sets_flood_wait_reason() -> None:
    """On a flood-wait the cooling account's last_error_reason == 'FLOOD_WAIT'
    (TASK-115 AC3)."""
    from .conftest import FakeFloodWaitError

    flooded = FakeClient(raise_on_entity=FakeFloodWaitError(seconds=10_000))
    other = FakeClient(messages=[make_message(3)])
    pool = make_pool([flooded, other])

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    collector = TelegramCollector(pool, sleep=fake_sleep)

    # A long flood (> inline cap) marks the account cooling and rotates; the read
    # eventually serves from `other`. Drain the generator.
    _ = [p async for p in collector.read([_REF], since=None)]

    statuses = {s.index: s for s in pool.account_statuses()}
    assert statuses[0].state == "cooling"
    assert statuses[0].last_error_reason == "FLOOD_WAIT"
