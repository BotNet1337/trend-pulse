"""TASK-031 — TwitterCollector unit tests (ФАЗА C, TDD).

AC1 — TwitterCollector implements the SourceCollector Protocol (@runtime_checkable).
AC2 — mapper maps X public_metrics → PostMetrics (like→reactions/retweet→forwards/
      impression→views; reply/quote/bookmark→extra); posted_at tz-aware UTC.
AC3 — registry: is_registered(TWITTER) is True; get without token → PoolConfigError.
read — yields mapped posts, dedups handles, ignores non-Twitter refs, filters `since`.
rate-limit — short 429 → sleep+retry once; long 429 → ref skipped (SourceUnavailable).
budget — monthly read budget exhausted → stop + alert ONCE; counter incremented.
client — TwitterHTTPClient parses v2 JSON via httpx.MockTransport (no network).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from collector.base import SourceCollector, SourceKind, SourceRef
from collector.errors import (
    PoolConfigError,
    SourceUnavailableError,
    TwitterAPIError,
    TwitterCreditsDepletedError,
    TwitterRateLimitError,
    TwitterReadBudgetExceededError,
)
from collector.twitter.client import TwitterHTTPClient, _Tweet
from collector.twitter.dedup import normalize_handle, unique_twitter_refs
from collector.twitter.mapper import map_tweet
from collector.twitter.reader import TwitterCollector

_REF = SourceRef(SourceKind.TWITTER, "acme")


def _tweet(
    tid: str, *, metrics: dict[str, int] | None = None, when: datetime | None = None
) -> _Tweet:
    return _Tweet(
        id=tid,
        text=f"tweet {tid}",
        created_at=when or datetime(2026, 6, 14, tzinfo=UTC),
        author="acme",
        public_metrics=metrics or {},
    )


class FakeTwitterClient:
    """In-memory TwitterClientProtocol — no network. Can raise on demand."""

    def __init__(
        self,
        *,
        user_id: str | None = "111",
        tweets: Sequence[_Tweet] | None = None,
        resolve_raises: Exception | None = None,
        fetch_raises: list[Exception | None] | None = None,
    ) -> None:
        self._user_id = user_id
        self._tweets = list(tweets if tweets is not None else [_tweet("7")])
        self._resolve_raises = resolve_raises
        # A queue of errors to raise on successive fetch calls (None = succeed).
        self._fetch_raises = list(fetch_raises or [])
        self.resolve_calls = 0
        self.fetch_calls = 0
        self.aclose_calls = 0
        self.last_start_time: datetime | None = None

    async def resolve_user_id(self, username: str) -> str | None:
        self.resolve_calls += 1
        if self._resolve_raises is not None:
            raise self._resolve_raises
        return self._user_id

    async def fetch_tweets(
        self,
        user_id: str,
        *,
        start_time: datetime | None,
        max_results: int,
        author: str | None = None,
    ) -> list[_Tweet]:
        self.fetch_calls += 1
        self.last_start_time = start_time
        if self._fetch_raises:
            err = self._fetch_raises.pop(0)
            if err is not None:
                raise err
        return [_Tweet(t.id, t.text, t.created_at, author, t.public_metrics) for t in self._tweets]

    async def aclose(self) -> None:
        self.aclose_calls += 1


# ---------------------------------------------------------------------------
# AC1 — Protocol conformance
# ---------------------------------------------------------------------------


def test_twitter_collector_implements_source_collector_protocol() -> None:
    collector = TwitterCollector(FakeTwitterClient())
    assert isinstance(collector, SourceCollector)
    assert collector.kind is SourceKind.TWITTER


# ---------------------------------------------------------------------------
# AC2 — mapper
# ---------------------------------------------------------------------------


def test_map_tweet_maps_public_metrics_and_extra() -> None:
    tweet = _tweet(
        "42",
        metrics={
            "like_count": 10,
            "retweet_count": 4,
            "impression_count": 1000,
            "reply_count": 3,
            "quote_count": 2,
            "bookmark_count": 1,
        },
    )
    post = map_tweet(tweet, _REF)
    assert post.external_id == "42"
    assert post.metrics.reactions == 10  # like_count
    assert post.metrics.forwards == 4  # retweet_count
    assert post.metrics.views == 1000  # impression_count
    assert post.metrics.extra == {"reply_count": 3, "quote_count": 2, "bookmark_count": 1}
    assert post.posted_at.tzinfo is not None  # tz-aware UTC
    assert post.source == _REF


def test_map_tweet_missing_metrics_default_zero_not_none() -> None:
    post = map_tweet(_tweet("1", metrics={}), _REF)
    assert post.metrics.views == 0
    assert post.metrics.forwards == 0
    assert post.metrics.reactions == 0


def test_map_tweet_naive_created_at_coerced_utc() -> None:
    naive = datetime(2026, 6, 14, 12, 0, 0)
    post = map_tweet(_tweet("1", when=naive), _REF)
    assert post.posted_at.tzinfo is UTC


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@Acme", "acme"),
        ("acme", "acme"),
        ("https://x.com/Acme", "acme"),
        ("https://twitter.com/acme", "acme"),
        ("  @ACME  ", "acme"),
        ("https://x.com/elonmusk/status/12345", "elonmusk"),  # tweet URL → username
        ("https://x.com/elonmusk?ref=home", "elonmusk"),  # query stripped
        ("https://x.com/elonmusk/", "elonmusk"),  # trailing slash
    ],
)
def test_normalize_handle(raw: str, expected: str) -> None:
    assert normalize_handle(raw) == expected


def test_unique_twitter_refs_dedups_and_ignores_non_twitter() -> None:
    refs = [
        SourceRef(SourceKind.TWITTER, "@Acme"),
        SourceRef(SourceKind.TWITTER, "acme"),  # dup after normalize
        SourceRef(SourceKind.TELEGRAM, "@acme"),  # ignored (not twitter)
        SourceRef(SourceKind.TWITTER, "other"),
    ]
    out = unique_twitter_refs(refs)
    assert [r.handle for r in out] == ["acme", "other"]


# ---------------------------------------------------------------------------
# validate_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_ref_true_when_resolved() -> None:
    collector = TwitterCollector(FakeTwitterClient(user_id="999"))
    assert await collector.validate_ref(_REF) is True


@pytest.mark.asyncio
async def test_validate_ref_false_when_not_found() -> None:
    collector = TwitterCollector(FakeTwitterClient(user_id=None))
    assert await collector.validate_ref(_REF) is False


@pytest.mark.asyncio
async def test_validate_ref_never_raises_on_client_error() -> None:
    collector = TwitterCollector(FakeTwitterClient(resolve_raises=TwitterAPIError("boom")))
    assert await collector.validate_ref(_REF) is False


@pytest.mark.asyncio
async def test_validate_ref_false_for_non_twitter_ref() -> None:
    collector = TwitterCollector(FakeTwitterClient())
    assert await collector.validate_ref(SourceRef(SourceKind.TELEGRAM, "@x")) is False


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_yields_mapped_posts() -> None:
    client = FakeTwitterClient(tweets=[_tweet("7"), _tweet("8")])
    collector = TwitterCollector(client)
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["7", "8"]
    assert all(p.source.kind is SourceKind.TWITTER for p in posts)


@pytest.mark.asyncio
async def test_read_dedups_same_handle() -> None:
    client = FakeTwitterClient(tweets=[_tweet("7")])
    collector = TwitterCollector(client)
    refs = [SourceRef(SourceKind.TWITTER, "@Acme"), SourceRef(SourceKind.TWITTER, "acme")]
    _ = [p async for p in collector.read(refs, since=None)]
    assert client.resolve_calls == 1  # read once despite two equivalent refs


@pytest.mark.asyncio
async def test_read_filters_tweets_older_than_since() -> None:
    since = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    old = _tweet("old", when=since - timedelta(hours=1))
    new = _tweet("new", when=since + timedelta(hours=1))
    collector = TwitterCollector(FakeTwitterClient(tweets=[old, new]))
    posts = [p async for p in collector.read([_REF], since=since)]
    assert [p.external_id for p in posts] == ["new"]


@pytest.mark.asyncio
async def test_read_skips_unresolved_account() -> None:
    collector = TwitterCollector(FakeTwitterClient(user_id=None))
    posts = [p async for p in collector.read([_REF], since=None)]
    assert posts == []


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rate_limit_sleeps_and_retries_once() -> None:
    # First fetch raises a short 429, retry succeeds.
    client = FakeTwitterClient(
        tweets=[_tweet("7")],
        fetch_raises=[TwitterRateLimitError("429", retry_after_seconds=5), None],
    )
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    collector = TwitterCollector(client, sleep=fake_sleep)
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["7"]
    assert slept == [5]
    assert client.fetch_calls == 2


@pytest.mark.asyncio
async def test_long_rate_limit_skips_ref() -> None:
    client = FakeTwitterClient(fetch_raises=[TwitterRateLimitError("429", retry_after_seconds=600)])
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    collector = TwitterCollector(client, sleep=fake_sleep)
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert slept == []  # never slept the long reset inline


# ---------------------------------------------------------------------------
# read budget
# ---------------------------------------------------------------------------


def _settings() -> object:
    from config import Settings

    return Settings.model_construct(
        ops_telegram_bot_token="tok",
        ops_telegram_chat_id="chat",
        ops_alert_throttle_seconds=3600,
        telegram_api_base_url="https://api.telegram.org",
        alert_http_timeout_seconds=10,
        jwt_secret="t",
        oauth_state_secret="t",
        google_client_id="t",
        google_client_secret="t",
    )


@pytest.mark.asyncio
async def test_read_budget_exhausted_stops_and_alerts_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collector.constants import MAX_TWITTER_READS_PER_MONTH

    redis = MagicMock()
    redis.get.return_value = str(MAX_TWITTER_READS_PER_MONTH)  # already at the cap
    redis.set.return_value = True

    sent: list[dict[str, object]] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent.append({"json": kwargs.get("json")})
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    collector = TwitterCollector(FakeTwitterClient(), settings=_settings(), redis=redis)
    for _ in range(3):  # multiple ticks — alert must fire only once
        with pytest.raises(TwitterReadBudgetExceededError):
            _ = [p async for p in collector.read([_REF], since=None)]

    assert len(sent) == 1, f"budget alert should fire once, got {len(sent)}"
    assert "лимит" in str(sent[0]["json"])


@pytest.mark.asyncio
async def test_read_budget_charges_counter_via_pipeline() -> None:
    # INCRBY + EXPIRE issued atomically in one pipeline (no TTL loss on crash).
    redis = MagicMock()
    redis.get.return_value = "0"
    pipe = redis.pipeline.return_value
    collector = TwitterCollector(FakeTwitterClient(tweets=[_tweet("7"), _tweet("8")]), redis=redis)
    _ = [p async for p in collector.read([_REF], since=None)]
    pipe.incrby.assert_called_once()
    assert pipe.incrby.call_args[0][1] == 2  # incremented by number of tweets read
    pipe.expire.assert_called_once()
    pipe.execute.assert_called_once()


@pytest.mark.asyncio
async def test_read_budget_alerts_again_after_month_rollover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collector.constants import MAX_TWITTER_READS_PER_MONTH

    redis = MagicMock()
    redis.get.return_value = str(MAX_TWITTER_READS_PER_MONTH)

    sent: list[object] = []

    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sent.append(kwargs.get("json"))
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)

    month = {"v": datetime(2026, 6, 1, tzinfo=UTC)}
    collector = TwitterCollector(
        FakeTwitterClient(), settings=_settings(), redis=redis, now=lambda: month["v"]
    )
    with pytest.raises(TwitterReadBudgetExceededError):
        _ = [p async for p in collector.read([_REF], since=None)]
    # Same month again → no second alert.
    with pytest.raises(TwitterReadBudgetExceededError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert len(sent) == 1
    # Month rollover → a fresh alert fires.
    month["v"] = datetime(2026, 7, 1, tzinfo=UTC)
    with pytest.raises(TwitterReadBudgetExceededError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_read_skips_ref_on_api_error_not_crash() -> None:
    # A non-rate-limit API error must surface as SourceUnavailableError (per-ref
    # skip the collect tick catches), NEVER the raw TwitterAPIError.
    client = FakeTwitterClient(fetch_raises=[TwitterAPIError("500 boom")])
    collector = TwitterCollector(client)
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]


# ---------------------------------------------------------------------------
# AC3 — registry
# ---------------------------------------------------------------------------


def test_registry_has_twitter_registered() -> None:
    from collector import registry

    assert registry.is_registered(SourceKind.TWITTER) is True


def test_build_twitter_collector_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector import registry

    monkeypatch.setattr("config.get_settings", lambda: SimpleNamespace(twitter_bearer_token=""))
    with pytest.raises(PoolConfigError):
        registry._build_twitter_collector()


# ---------------------------------------------------------------------------
# client (httpx.MockTransport — no network)
# ---------------------------------------------------------------------------


def _client_with(handler) -> TwitterHTTPClient:
    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    return TwitterHTTPClient(bearer_token="tok", base_url="https://api.twitter.com", client=ac)


@pytest.mark.asyncio
async def test_client_resolve_user_id_parses_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"data": {"id": "555", "username": "acme"}})

    client = _client_with(handler)
    assert await client.resolve_user_id("acme") == "555"
    await client.aclose()


@pytest.mark.asyncio
async def test_client_resolve_user_id_404_returns_none() -> None:
    client = _client_with(lambda req: httpx.Response(404, json={}))
    assert await client.resolve_user_id("ghost") is None
    await client.aclose()


@pytest.mark.asyncio
async def test_client_429_raises_rate_limit() -> None:
    client = _client_with(lambda req: httpx.Response(429, headers={"x-rate-limit-reset": "0"}))
    with pytest.raises(TwitterRateLimitError):
        await client.resolve_user_id("acme")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_fetch_tweets_parses_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "7",
                        "text": "hi",
                        "created_at": "2026-06-14T13:01:59.000Z",
                        "public_metrics": {"like_count": 5, "retweet_count": 2},
                    }
                ]
            },
        )

    client = _client_with(handler)
    tweets = await client.fetch_tweets("111", start_time=None, max_results=10, author="acme")
    assert len(tweets) == 1
    assert tweets[0].id == "7"
    assert tweets[0].author == "acme"
    assert tweets[0].public_metrics["like_count"] == 5
    assert tweets[0].created_at == datetime(2026, 6, 14, 13, 1, 59, tzinfo=UTC)
    await client.aclose()


@pytest.mark.asyncio
async def test_client_server_error_raises_api_error() -> None:
    client = _client_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(TwitterAPIError):
        await client.fetch_tweets("111", start_time=None, max_results=10)
    await client.aclose()


# ---------------------------------------------------------------------------
# Cost controls: 402 credits cooldown, per-account interval, user-id cache
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Tiny dict-backed Redis fake (distinguishes keys, unlike a single MagicMock)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(
        self, key: str, value: object, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        # Mimic SET NX: return None if the key already exists (throttle "not acquired").
        if nx and key in self.store:
            return None
        self.store[key] = str(value)
        return True

    def incrby(self, key: str, n: int) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + n)
        return int(self.store[key])

    def expire(self, key: str, ttl: int) -> bool:
        return True

    def pipeline(self) -> _FakePipe:
        return _FakePipe(self)


class _FakePipe:
    def __init__(self, r: _FakeRedis) -> None:
        self._r = r
        self._ops: list[tuple[str, str, int]] = []

    def incrby(self, key: str, n: int) -> _FakePipe:
        self._ops.append(("incrby", key, n))
        return self

    def expire(self, key: str, ttl: int) -> _FakePipe:
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self) -> None:
        for op, key, val in self._ops:
            if op == "incrby":
                self._r.incrby(key, val)
        self._ops = []


def _capture_ops_post(monkeypatch: pytest.MonkeyPatch, sink: list[object]) -> None:
    def _fake_post(url: str, **kwargs: object) -> MagicMock:
        sink.append(kwargs.get("json"))
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr("observability.pool_health.httpx.post", _fake_post)


@pytest.mark.asyncio
async def test_credits_depleted_pauses_reads_and_alerts_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # First account hits 402 → cooldown entered, ref skipped; subsequent reads during
    # cooldown make NO API calls and alert fires exactly once.
    client = FakeTwitterClient(fetch_raises=[TwitterCreditsDepletedError("402")])
    redis = _FakeRedis()
    sent: list[object] = []
    _capture_ops_post(monkeypatch, sent)
    clock = {"t": 1000.0}
    collector = TwitterCollector(
        client, settings=_settings(), redis=redis, monotonic=lambda: clock["t"]
    )

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    calls_after_first = client.resolve_calls + client.fetch_calls

    # A later tick within cooldown: read() returns immediately, no API calls.
    posts = [p async for p in collector.read([SourceRef(SourceKind.TWITTER, "other")], since=None)]
    assert posts == []
    assert client.resolve_calls + client.fetch_calls == calls_after_first  # no new calls

    credits_alerts = [s for s in sent if "кредит" in str(s) or "402" in str(s)]
    assert len(credits_alerts) == 1


@pytest.mark.asyncio
async def test_credits_cooldown_expires_resumes_reads() -> None:
    from collector.constants import (
        TWITTER_CREDITS_COOLDOWN_SECONDS,
        TWITTER_MIN_READ_INTERVAL_SECONDS,
    )

    # resolve always 402s; we verify the API is NOT hit during the pause and IS hit
    # again once both the pause AND the per-account interval elapse (reads resume).
    client = FakeTwitterClient(resolve_raises=TwitterCreditsDepletedError("402"))
    redis = _FakeRedis()
    mono = {"t": 1000.0}
    epoch = {"t": 1_000_000.0}
    collector = TwitterCollector(
        client,
        redis=redis,
        monotonic=lambda: mono["t"],
        now=lambda: datetime.fromtimestamp(epoch["t"], tz=UTC),
    )

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert client.resolve_calls == 1  # attempted once

    # Within pause: no API call.
    posts = [p async for p in collector.read([_REF], since=None)]
    assert posts == []
    assert client.resolve_calls == 1  # unchanged — paused

    # After pause + interval: reads resume (API hit again).
    step = max(TWITTER_CREDITS_COOLDOWN_SECONDS, TWITTER_MIN_READ_INTERVAL_SECONDS) + 1
    mono["t"] += step
    epoch["t"] += step
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert client.resolve_calls == 2  # resumed


@pytest.mark.asyncio
async def test_failing_account_not_repolled_within_interval() -> None:
    # A failing account (generic API error) must be stamped so it is NOT re-polled
    # every tick — the cost/rate-limit safety fix.
    client = FakeTwitterClient(resolve_raises=TwitterAPIError("500"))
    redis = _FakeRedis()
    epoch = {"t": 1_000_000.0}
    collector = TwitterCollector(
        client, redis=redis, now=lambda: datetime.fromtimestamp(epoch["t"], tz=UTC)
    )

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert client.resolve_calls == 1

    # Immediate next tick: account is within its interval → skipped, NO API call.
    posts = [p async for p in collector.read([_REF], since=None)]
    assert posts == []
    assert client.resolve_calls == 1  # not re-polled


@pytest.mark.asyncio
async def test_long_429_pauses_all_reads() -> None:
    # A long 429 reset pauses ALL reads (not just a per-ref skip) so the other
    # accounts don't each hit 429 this tick.
    client = FakeTwitterClient(resolve_raises=TwitterRateLimitError("429", retry_after_seconds=600))
    redis = _FakeRedis()
    collector = TwitterCollector(client, redis=redis, monotonic=lambda: 1000.0)

    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert client.resolve_calls == 1

    # A different account in the same paused window: no API call.
    posts = [p async for p in collector.read([SourceRef(SourceKind.TWITTER, "other")], since=None)]
    assert posts == []
    assert client.resolve_calls == 1


@pytest.mark.asyncio
async def test_account_skipped_within_min_interval_and_userid_cached() -> None:
    from collector.constants import TWITTER_MIN_READ_INTERVAL_SECONDS

    client = FakeTwitterClient(tweets=[_tweet("7")])
    redis = _FakeRedis()
    epoch = {"t": 1_000_000.0}
    collector = TwitterCollector(
        client, redis=redis, now=lambda: datetime.fromtimestamp(epoch["t"], tz=UTC)
    )

    # First read: resolves, fetches, stamps last-read + caches user-id.
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["7"]
    assert client.fetch_calls == 1
    assert client.resolve_calls == 1

    # Immediate second read (within interval): skipped, no API calls.
    posts2 = [p async for p in collector.read([_REF], since=None)]
    assert posts2 == []
    assert client.fetch_calls == 1
    assert client.resolve_calls == 1

    # Past the interval: reads again, but user-id is cached → resolve NOT repeated.
    epoch["t"] += TWITTER_MIN_READ_INTERVAL_SECONDS + 1
    posts3 = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts3] == ["7"]
    assert client.fetch_calls == 2
    assert client.resolve_calls == 1  # cached


@pytest.mark.asyncio
async def test_client_402_raises_credits_depleted() -> None:
    client = _client_with(lambda req: httpx.Response(402, json={"title": "CreditsDepleted"}))
    with pytest.raises(TwitterCreditsDepletedError):
        await client.resolve_user_id("jack")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_malformed_json_raises_api_error() -> None:
    # 200 with a non-JSON body (CDN/proxy error page) → TwitterAPIError, not a raw
    # ValueError escaping the collector domain.
    client = _client_with(lambda req: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(TwitterAPIError):
        await client.resolve_user_id("acme")
    await client.aclose()


@pytest.mark.asyncio
async def test_read_yields_tweets_within_window_not_caller_since() -> None:
    # REGRESSION: a tweet older than the caller's ~60s tick `since` but within the
    # floored effective window MUST be yielded. The post-loop cutoff must use
    # effective_since, not `since` — using `since` discarded everything the wider
    # window fetched (every read yielded 0 posts in prod).
    now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    ten_min_ago = now - timedelta(minutes=10)
    client = FakeTwitterClient(tweets=[_tweet("t10", when=ten_min_ago)])
    redis = _FakeRedis()
    collector = TwitterCollector(client, redis=redis, now=lambda: now)

    narrow = now - timedelta(seconds=60)  # the shared tick's ~60s marker
    posts = [p async for p in collector.read([_REF], since=narrow)]
    assert [p.external_id for p in posts] == ["t10"]  # NOT filtered by the narrow since
