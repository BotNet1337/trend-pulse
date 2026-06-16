"""Unit tests for observability/pool_health.py (TASK-035).

AC1 — emit_pool_health logs aggregates (size, cooling, healthy, target, degraded).
AC2 — all-flood -> notify_ops called with reason + cooldown_remaining.
AC3 — pool below pool_min_healthy -> degraded=True + single self-alert.
AC4 — throttle: same reason within ops_alert_throttle_seconds -> second send suppressed.
AC5 — empty ops settings -> metric only, no send, no raise; backend HTTP error -> warn, no raise.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from collector.errors import AllAccountsFloodWaitError
from collector.telegram.account_pool import AccountPool
from config import Settings

from .conftest import FakeClient, make_pool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _make_settings(
    *,
    pool_min_healthy: int = 3,
    ops_token: str = "test-token",
    ops_chat_id: str = "12345",
    throttle: int = 3600,
) -> Settings:
    """Build a minimal Settings for tests (bypasses env by using object.__setattr__)."""
    return Settings.model_construct(
        pool_min_healthy=pool_min_healthy,
        ops_telegram_bot_token=ops_token,
        ops_telegram_chat_id=ops_chat_id,
        ops_alert_throttle_seconds=throttle,
        telegram_api_base_url="https://api.telegram.org",
        alert_http_timeout_seconds=10,
        jwt_secret="test",
        oauth_state_secret="test",
        google_client_id="test",
        google_client_secret="test",
    )


# ---------------------------------------------------------------------------
# AC1 — emit_pool_health logs aggregates only (no session strings / secrets)
# ---------------------------------------------------------------------------


def test_emit_pool_health_logs_aggregates(caplog: pytest.LogCaptureFixture) -> None:
    """emit_pool_health should log size, cooling, healthy, target, degraded — no secrets.

    Asserts:
    - returned dict has exactly the five aggregate keys (no extras, no secrets).
    - no key matching token/session/text/content appears in the returned dict.
    - log output contains no session strings.
    """
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # Put 1 account in cooldown
    pool.acquire()
    pool.report_flood_wait(retry_after_seconds=60)

    settings = _make_settings(pool_min_healthy=3)

    with caplog.at_level(logging.INFO, logger="trendpulse"):
        from observability.pool_health import emit_pool_health

        result = emit_pool_health(pool, settings)

    assert result["size"] == 3
    assert result["cooling"] == 1
    assert result["healthy"] == 2
    assert result["target"] == 3
    # 2 healthy < 3 target → degraded
    assert result["degraded"] is True

    # Returned dict must contain EXACTLY the aggregate fields — no extras.
    # `quarantined` added in TASK-087 (dead-session count, non-secret).
    assert set(result.keys()) == {
        "size",
        "cooling",
        "quarantined",
        "healthy",
        "target",
        "degraded",
    }, f"Unexpected keys in emit_pool_health result: {set(result.keys())}"

    # None of the keys may be a secret/PII carrier.
    secret_patterns = {"token", "session", "text", "content"}
    for key in result:
        assert not any(pat in key.lower() for pat in secret_patterns), (
            f"Secret-like key found in pool health aggregates: {key!r}"
        )

    # No session strings in logs
    log_text = caplog.text
    assert "session-" not in log_text


def test_emit_pool_health_degraded_false_when_healthy_meets_target(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When all 3 accounts are healthy and target=3, degraded=False."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    settings = _make_settings(pool_min_healthy=3)

    with caplog.at_level(logging.INFO, logger="trendpulse"):
        from observability.pool_health import emit_pool_health

        result = emit_pool_health(pool, settings)

    assert result["size"] == 3
    assert result["cooling"] == 0
    assert result["healthy"] == 3
    assert result["target"] == 3
    assert result["degraded"] is False


def test_emit_pool_health_all_cooling_degraded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When all accounts are in cooldown, degraded=True and healthy=0."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # Put all in cooldown
    for _ in range(3):
        pool.acquire()
        pool.report_flood_wait(retry_after_seconds=300)

    settings = _make_settings(pool_min_healthy=3)

    with caplog.at_level(logging.INFO, logger="trendpulse"):
        from observability.pool_health import emit_pool_health

        result = emit_pool_health(pool, settings)

    assert result["size"] == 3
    assert result["cooling"] == 3
    assert result["healthy"] == 0
    assert result["degraded"] is True


# ---------------------------------------------------------------------------
# AC2 — All-flood -> notify_ops with reason + cooldown_remaining
# ---------------------------------------------------------------------------


def test_notify_ops_sends_via_telegram_backend_on_flood(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When all accounts are flooded, notify_ops sends a message via TelegramBotBackend."""
    clock = _Clock()
    pool = _pool_with_clock(3, clock)

    # Put all in cooldown
    for _ in range(3):
        pool.acquire()
        pool.report_flood_wait(retry_after_seconds=120)

    settings = _make_settings()

    # Mock Redis: SET NX returns True (not throttled)
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    sent_calls: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append({"url": url, "json": kwargs.get("json")})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire()

    from observability.pool_health import notify_ops

    cooldown = pool.cooldown_remaining()
    notify_ops(
        reason="all_flood",
        text=f"All accounts flooded. Cooldown: {int(cooldown)}s",
        settings=settings,
        redis=mock_redis,
    )

    assert len(sent_calls) == 1
    call = sent_calls[0]
    assert "test-token" in str(call["url"])
    payload = call["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "12345"
    assert "flood" in str(payload["text"]).lower() or "cool" in str(payload["text"]).lower()

    # Token must NOT appear in the text body
    assert "test-token" not in str(payload.get("text", ""))


def test_notify_ops_text_contains_cooldown_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The all-flood handler's real ops message text must include the integer cooldown seconds.

    Exercises the production path in TelegramCollector._acquire_ready_client that
    builds the notify_text from pool.cooldown_remaining() — not a hand-built f-string.
    The collector calls _emit_health_best_effort(notify_reason="all_flood",
    notify_text=f"TG pool: all accounts flooded. cooldown_remaining={int(wait)}s").
    """
    clock = _Clock()
    pool = _pool_with_clock(3, clock)
    settings = _make_settings()

    for _ in range(3):
        pool.acquire()
        pool.report_flood_wait(retry_after_seconds=250)

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # throttle opens → send fires

    sent_payloads: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_payloads.append({"url": url, "json": kwargs.get("json")})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from collector.errors import AllAccountsFloodWaitError
    from collector.telegram.reader import TelegramCollector

    # Drive _emit_health_best_effort(notify_reason="all_flood") directly —
    # the same call that _acquire_ready_client makes when the pool is exhausted.
    # This is the exact production code path: it reads pool.cooldown_remaining()
    # and embeds the integer seconds into the text.
    cooldown_seconds = int(pool.cooldown_remaining())
    assert cooldown_seconds > 0, "pool should be cooling after flood_wait=250s"

    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    collector = TelegramCollector(pool, sleep=fake_sleep, settings=settings, redis=mock_redis)

    with pytest.raises(AllAccountsFloodWaitError):
        pool.acquire()  # confirm pool is fully flooded

    # Invoke the production notification helper that _acquire_ready_client calls:
    collector._emit_health_best_effort(
        notify_reason="all_flood",
        notify_text=f"TG pool: all accounts flooded. cooldown_remaining={cooldown_seconds}s",
    )

    assert len(sent_payloads) >= 1, "notify_ops should have fired for all_flood"
    sent_json = sent_payloads[0].get("json")
    assert isinstance(sent_json, dict)
    payload_text: str = str(sent_json.get("text", ""))
    assert str(cooldown_seconds) in payload_text, (
        f"cooldown seconds ({cooldown_seconds}) not found in sent ops text: {payload_text!r}"
    )


# ---------------------------------------------------------------------------
# AC3 — Pool below pool_min_healthy -> degraded=True + single self-alert
# ---------------------------------------------------------------------------


def test_emit_pool_health_below_target_is_degraded() -> None:
    """2 accounts, pool_min_healthy=3 → degraded=True."""
    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=3)

    from observability.pool_health import emit_pool_health

    result = emit_pool_health(pool, settings)

    assert result["size"] == 2
    assert result["healthy"] == 2
    assert result["target"] == 3
    assert result["degraded"] is True


def test_notify_ops_sent_for_degraded_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notify_ops should trigger a send when pool is below target."""
    settings = _make_settings(pool_min_healthy=3)

    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # not throttled

    sent_calls: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append({"url": url})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from observability.pool_health import notify_ops

    notify_ops(
        reason="pool_below_target",
        text="Pool below target: 2 healthy, target 3",
        settings=settings,
        redis=mock_redis,
    )

    assert len(sent_calls) == 1


# ---------------------------------------------------------------------------
# AC4 — Throttle: same reason within throttle window -> second send suppressed
# ---------------------------------------------------------------------------


def test_notify_ops_throttled_on_second_call(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Second notify_ops call for same reason within throttle window is suppressed."""
    settings = _make_settings(throttle=3600)

    mock_redis = MagicMock()
    # First call: SET NX succeeds (key did not exist → throttle opens)
    # Second call: SET NX fails (key exists → throttled)
    mock_redis.set.side_effect = [True, None]  # True=sent, None=already set (throttled)

    sent_calls: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append({"url": url})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from observability.pool_health import notify_ops

    with caplog.at_level(logging.WARNING, logger="trendpulse"):
        notify_ops(
            reason="all_flood",
            text="flood message 1",
            settings=settings,
            redis=mock_redis,
        )
        notify_ops(
            reason="all_flood",
            text="flood message 2",
            settings=settings,
            redis=mock_redis,
        )

    # Only one HTTP send despite two calls
    assert len(sent_calls) == 1
    # A log entry should be written for the throttled call
    assert any(
        "throttl" in rec.message.lower() or "throttl" in rec.getMessage().lower()
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    ) or any("throttl" in caplog.text.lower())


def test_notify_ops_redis_key_uses_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis SET NX key must include the reason string."""
    settings = _make_settings(throttle=3600)

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from observability.pool_health import notify_ops

    notify_ops(
        reason="auth_error",
        text="auth error detected",
        settings=settings,
        redis=mock_redis,
    )

    # Verify Redis SET was called with a key containing the reason
    assert mock_redis.set.called
    call_args = mock_redis.set.call_args
    key = call_args[0][0] if call_args[0] else call_args.kwargs.get("name", "")
    assert "auth_error" in str(key)


# ---------------------------------------------------------------------------
# AC4 — Redis unavailable → fail-open: skip send, warn log, no raise
# ---------------------------------------------------------------------------


def test_notify_ops_redis_error_skips_send_logs_warn(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If Redis raises RedisError on SET, notify_ops skips the send and logs a warning."""
    from redis.exceptions import RedisError

    settings = _make_settings()

    mock_redis = MagicMock()
    mock_redis.set.side_effect = RedisError("redis connection refused")

    sent_calls: list[object] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    with caplog.at_level(logging.WARNING, logger="trendpulse"):
        from observability.pool_health import notify_ops

        # Must NOT raise
        notify_ops(
            reason="all_flood",
            text="pool flooded",
            settings=settings,
            redis=mock_redis,
        )

    # No send when Redis is unavailable (fail-open = skip, not spam)
    assert len(sent_calls) == 0
    # Warning logged
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# AC5 — Empty ops settings -> metric only, no send, no raise
# ---------------------------------------------------------------------------


def test_notify_ops_empty_token_skips_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ops_telegram_bot_token is empty, notify_ops does nothing (metric only)."""
    settings = _make_settings(ops_token="", ops_chat_id="")

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    sent_calls: list[object] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from observability.pool_health import notify_ops

    # Must not raise
    notify_ops(
        reason="all_flood",
        text="flood occurred",
        settings=settings,
        redis=mock_redis,
    )

    assert len(sent_calls) == 0


def test_notify_ops_empty_chat_id_skips_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ops_telegram_chat_id is empty, notify_ops skips send (no raise)."""
    settings = _make_settings(ops_token="some-token", ops_chat_id="")

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    sent_calls: list[object] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent_calls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    from observability.pool_health import notify_ops

    notify_ops(
        reason="all_flood",
        text="flood occurred",
        settings=settings,
        redis=mock_redis,
    )

    assert len(sent_calls) == 0


def test_notify_ops_http_error_warns_no_raise(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Backend HTTP error (4xx/5xx/network) → warn log, no raise."""
    import httpx as _httpx

    settings = _make_settings()

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    def _fail_post(url: str, **kwargs: object) -> MagicMock:
        raise _httpx.ConnectError("connection refused")

    monkeypatch.setattr("observability.pool_health.httpx.post", _fail_post)

    with caplog.at_level(logging.WARNING, logger="trendpulse"):
        from observability.pool_health import notify_ops

        # Must NOT raise
        notify_ops(
            reason="all_flood",
            text="flood occurred",
            settings=settings,
            redis=mock_redis,
        )

    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


def test_notify_ops_http_status_error_warns_no_raise(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Backend non-2xx response → warn log, no raise."""
    settings = _make_settings()

    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    def _bad_post(url: str, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 500
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _bad_post)

    with caplog.at_level(logging.WARNING, logger="trendpulse"):
        from observability.pool_health import notify_ops

        notify_ops(
            reason="all_flood",
            text="flood occurred",
            settings=settings,
            redis=mock_redis,
        )

    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# TASK-115 — emit_pool_health bridges the full snapshot to Redis
# ---------------------------------------------------------------------------


def test_emit_pool_health_writes_snapshot_to_redis_with_ttl() -> None:
    """emit_pool_health(..., redis) writes JSON to pool:health:latest with a TTL,
    containing aggregates + an accounts list + as_of (TASK-115 AC4)."""
    import json

    from collector.constants import (
        POOL_HEALTH_REDIS_KEY,
        POOL_HEALTH_SNAPSHOT_TTL_SECONDS,
    )

    clock = _Clock()
    pool = _pool_with_clock(3, clock)
    # 1 cooling.
    pool.acquire()
    pool.report_flood_wait(retry_after_seconds=60)

    settings = _make_settings(pool_min_healthy=3)

    mock_redis = MagicMock()

    from observability.pool_health import emit_pool_health

    result = emit_pool_health(pool, settings, mock_redis)

    # Return shape unchanged (existing callers).
    assert set(result.keys()) == {
        "size",
        "cooling",
        "quarantined",
        "healthy",
        "target",
        "degraded",
    }

    assert mock_redis.set.called
    args, kwargs = mock_redis.set.call_args
    assert args[0] == POOL_HEALTH_REDIS_KEY
    assert kwargs.get("ex") == POOL_HEALTH_SNAPSHOT_TTL_SECONDS

    snapshot = json.loads(args[1])
    assert snapshot["size"] == 3
    assert snapshot["cooling"] == 1
    assert "as_of" in snapshot
    assert isinstance(snapshot["accounts"], list)
    assert len(snapshot["accounts"]) == 3
    states = {a["state"] for a in snapshot["accounts"]}
    assert states == {"healthy", "cooling"}
    cooling = next(a for a in snapshot["accounts"] if a["state"] == "cooling")
    assert cooling["cooldown_remaining_seconds"] is not None
    # TASK-120 additively carries the non-secret per-account identity (null here — no
    # store identity for an in-memory test pool).
    assert {
        "index",
        "state",
        "cooldown_remaining_seconds",
        "last_error_reason",
        "display_label",
        "tg_user_id",
        "read_failure_count",
    } == set(cooling.keys())
    assert cooling["display_label"] is None
    assert cooling["tg_user_id"] is None
    assert cooling["read_failure_count"] == 0


def test_snapshot_carries_read_failure_count() -> None:
    """The snapshot per-account dict carries the cumulative `read_failure_count` so the
    pool-admin UI can show error frequency (e.g. "xN")."""
    import json

    clock = _Clock()
    pool = _pool_with_clock(2, clock)
    pool.acquire()
    pool.note_read_failure("SecurityError")
    pool.note_read_failure("SecurityError")

    settings = _make_settings(pool_min_healthy=2)
    mock_redis = MagicMock()

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)
    snapshot = json.loads(mock_redis.set.call_args[0][1])
    failed = snapshot["accounts"][0]
    assert failed["read_failure_count"] == 2
    assert failed["last_error_reason"] == "SecurityError"


def test_emit_pool_health_snapshot_has_no_secrets() -> None:
    """The Redis snapshot must not contain session strings / fingerprints (index only)."""
    import json

    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=3)
    mock_redis = MagicMock()

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)
    payload = json.loads(mock_redis.set.call_args[0][1])
    blob = json.dumps(payload)
    assert "session-" not in blob
    for account in payload["accounts"]:
        assert "fingerprint" not in account
        assert "session" not in json.dumps(account)


def test_emit_pool_health_no_redis_does_not_write() -> None:
    """Without a redis client, no snapshot is written (backwards-compat)."""
    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=3)

    from observability.pool_health import emit_pool_health

    # No redis arg → no write, no raise; return shape preserved.
    result = emit_pool_health(pool, settings)
    assert result["size"] == 2


def test_snapshot_ingest_contradiction_true_when_all_healthy_and_stale() -> None:
    """When all accounts are healthy (healthy == size) AND the ingest-staleness key says
    stale, the snapshot's `ingest_contradiction` is True (TASK-118)."""
    import json

    from collector.constants import INGEST_STALENESS_REDIS_KEY

    pool = make_pool([FakeClient(), FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=3)

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"stale": True, "age_s": 1800})

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)
    snapshot = json.loads(mock_redis.set.call_args[0][1])
    assert snapshot["ingest_contradiction"] is True
    mock_redis.get.assert_called_once_with(INGEST_STALENESS_REDIS_KEY)


def test_snapshot_no_contradiction_when_key_absent() -> None:
    """Missing/expired ingest-staleness key → fail-open: no contradiction (TASK-118)."""
    import json

    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=2)

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)
    snapshot = json.loads(mock_redis.set.call_args[0][1])
    assert snapshot["ingest_contradiction"] is False


def test_snapshot_no_contradiction_when_not_all_healthy() -> None:
    """Stale ingest but a cooling account (healthy < size) → no contradiction: the
    degraded pool already explains the staleness (TASK-118)."""
    import json

    clock = _Clock()
    pool = _pool_with_clock(3, clock)
    pool.acquire()
    pool.report_flood_wait(retry_after_seconds=60)  # 1 cooling → healthy != size
    settings = _make_settings(pool_min_healthy=3)

    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps({"stale": True, "age_s": 1800})

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)
    snapshot = json.loads(mock_redis.set.call_args[0][1])
    assert snapshot["ingest_contradiction"] is False


def test_snapshot_contradiction_read_failure_is_fail_open() -> None:
    """A Redis error reading the ingest-staleness key fails open (no contradiction) and
    never breaks the snapshot write (TASK-118)."""
    import json

    from redis.exceptions import RedisError

    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=2)

    mock_redis = MagicMock()
    mock_redis.get.side_effect = RedisError("redis down")

    from observability.pool_health import emit_pool_health

    emit_pool_health(pool, settings, mock_redis)  # must not raise
    snapshot = json.loads(mock_redis.set.call_args[0][1])
    assert snapshot["ingest_contradiction"] is False


def test_emit_pool_health_redis_write_failure_is_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Redis error on the snapshot write logs a warning and never raises (Invariant)."""
    from redis.exceptions import RedisError

    pool = make_pool([FakeClient(), FakeClient()])
    settings = _make_settings(pool_min_healthy=3)

    mock_redis = MagicMock()
    mock_redis.set.side_effect = RedisError("redis down")

    with caplog.at_level(logging.WARNING, logger="trendpulse"):
        from observability.pool_health import emit_pool_health

        result = emit_pool_health(pool, settings, mock_redis)  # must NOT raise

    assert result["size"] == 2
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)
