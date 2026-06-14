"""TASK-092 — RedditCollector unit tests (reddit-loop ФАЗА R, TDD).

AC1 — RedditCollector implements the SourceCollector Protocol (@runtime_checkable).
AC2 — mapper maps a submission → PostMetrics (score→reactions/num_crossposts→
      forwards/views=0; num_comments/upvote_ratio_pct/total_awards_received→extra);
      posted_at tz-aware UTC.
AC3 — OAuth2 token fetch/refresh + registry: is_registered(REDDIT) is True; build
      without creds → PoolConfigError.
AC4 — read yields mapped posts, dedups subreddits, ignores non-Reddit refs, filters `since`.
AC5 — rate-limit: short 429 → sleep+retry once; long 429 → ref skipped (SourceUnavailable);
      no read budget (Reddit is free).
client — RedditHTTPClient does OAuth2 + parses JSON via httpx.MockTransport (no network).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from collector.base import SourceCollector, SourceKind, SourceRef
from collector.errors import (
    PoolConfigError,
    RedditAPIError,
    RedditAuthError,
    RedditRateLimitError,
    SourceUnavailableError,
)
from collector.reddit.client import RedditHTTPClient, _Submission
from collector.reddit.dedup import normalize_handle, unique_reddit_refs
from collector.reddit.mapper import map_submission
from collector.reddit.reader import RedditCollector

_REF = SourceRef(SourceKind.REDDIT, "cryptocurrency")


def _submission(
    sid: str,
    *,
    score: int = 0,
    num_crossposts: int = 0,
    num_comments: int = 0,
    upvote_ratio: float = 0.0,
    total_awards_received: int = 0,
    when: datetime | None = None,
    title: str | None = None,
    selftext: str | None = None,
) -> _Submission:
    return _Submission(
        external_id=f"t3_{sid}",
        title=title if title is not None else f"post {sid}",
        selftext=selftext,
        created_utc=when or datetime(2026, 6, 14, tzinfo=UTC),
        author="someuser",
        score=score,
        num_crossposts=num_crossposts,
        num_comments=num_comments,
        upvote_ratio=upvote_ratio,
        total_awards_received=total_awards_received,
    )


class FakeRedditClient:
    """In-memory RedditClientProtocol — no network. Can raise on demand."""

    def __init__(
        self,
        *,
        exists: bool = True,
        submissions: Sequence[_Submission] | None = None,
        exists_raises: Exception | None = None,
        fetch_raises: list[Exception | None] | None = None,
    ) -> None:
        self._exists = exists
        self._submissions = list(submissions if submissions is not None else [_submission("7")])
        self._exists_raises = exists_raises
        self._fetch_raises = list(fetch_raises or [])
        self.exists_calls = 0
        self.fetch_calls = 0
        self.aclose_calls = 0

    async def subreddit_exists(self, name: str) -> bool:
        self.exists_calls += 1
        if self._exists_raises is not None:
            raise self._exists_raises
        return self._exists

    async def fetch_new(self, name: str, *, limit: int) -> list[_Submission]:
        self.fetch_calls += 1
        if self._fetch_raises:
            err = self._fetch_raises.pop(0)
            if err is not None:
                raise err
        return list(self._submissions)

    async def aclose(self) -> None:
        self.aclose_calls += 1


# ---------------------------------------------------------------------------
# AC1 — Protocol conformance
# ---------------------------------------------------------------------------


def test_reddit_collector_implements_source_collector_protocol() -> None:
    collector = RedditCollector(FakeRedditClient())
    assert isinstance(collector, SourceCollector)
    assert collector.kind is SourceKind.REDDIT


# ---------------------------------------------------------------------------
# AC2 — mapper
# ---------------------------------------------------------------------------


def test_map_submission_maps_metrics_and_extra() -> None:
    sub = _submission(
        "42",
        score=120,
        num_crossposts=4,
        num_comments=33,
        upvote_ratio=0.95,
        total_awards_received=2,
        title="big news",
        selftext="body text",
    )
    post = map_submission(sub, _REF)
    assert post.external_id == "t3_42"
    assert post.metrics.reactions == 120  # score (ups)
    assert post.metrics.forwards == 4  # num_crossposts
    assert post.metrics.views == 0  # Reddit exposes no impressions
    assert post.metrics.extra == {
        "num_comments": 33,
        "upvote_ratio_pct": 95,
        "total_awards_received": 2,
    }
    assert post.text == "big news\n\nbody text"
    assert post.posted_at.tzinfo is not None  # tz-aware UTC
    assert post.source == _REF


def test_map_submission_missing_metrics_default_zero_not_none() -> None:
    post = map_submission(_submission("1"), _REF)
    assert post.metrics.views == 0
    assert post.metrics.forwards == 0
    assert post.metrics.reactions == 0
    assert post.metrics.extra["upvote_ratio_pct"] == 0


def test_map_submission_naive_created_utc_coerced_utc() -> None:
    naive = datetime(2026, 6, 14, 12, 0, 0)
    post = map_submission(_submission("1", when=naive), _REF)
    assert post.posted_at.tzinfo is UTC


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("r/CryptoCurrency", "cryptocurrency"),
        ("cryptocurrency", "cryptocurrency"),
        ("CryptoCurrency", "cryptocurrency"),
        ("https://www.reddit.com/r/CryptoCurrency", "cryptocurrency"),
        ("https://reddit.com/r/Bitcoin", "bitcoin"),
        ("  r/ETHTrader  ", "ethtrader"),
        ("https://www.reddit.com/r/Bitcoin/comments/abc/title/", "bitcoin"),  # post URL → sub
        ("https://www.reddit.com/r/Bitcoin?ref=home", "bitcoin"),  # query stripped
        ("/r/defi/", "defi"),  # leading + trailing slash
    ],
)
def test_normalize_handle(raw: str, expected: str) -> None:
    assert normalize_handle(raw) == expected


def test_unique_reddit_refs_dedups_and_ignores_non_reddit() -> None:
    refs = [
        SourceRef(SourceKind.REDDIT, "r/CryptoCurrency"),
        SourceRef(SourceKind.REDDIT, "cryptocurrency"),  # dup after normalize
        SourceRef(SourceKind.TELEGRAM, "@cryptocurrency"),  # ignored (not reddit)
        SourceRef(SourceKind.REDDIT, "Bitcoin"),
    ]
    out = unique_reddit_refs(refs)
    assert [r.handle for r in out] == ["cryptocurrency", "bitcoin"]


# ---------------------------------------------------------------------------
# validate_ref
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_ref_true_when_subreddit_exists() -> None:
    collector = RedditCollector(FakeRedditClient(exists=True))
    assert await collector.validate_ref(_REF) is True


@pytest.mark.asyncio
async def test_validate_ref_false_when_not_found() -> None:
    collector = RedditCollector(FakeRedditClient(exists=False))
    assert await collector.validate_ref(_REF) is False


@pytest.mark.asyncio
async def test_validate_ref_never_raises_on_client_error() -> None:
    collector = RedditCollector(FakeRedditClient(exists_raises=RedditAPIError("boom")))
    assert await collector.validate_ref(_REF) is False


@pytest.mark.asyncio
async def test_validate_ref_false_for_non_reddit_ref() -> None:
    collector = RedditCollector(FakeRedditClient())
    assert await collector.validate_ref(SourceRef(SourceKind.TELEGRAM, "@x")) is False


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_yields_mapped_posts() -> None:
    client = FakeRedditClient(submissions=[_submission("7"), _submission("8")])
    collector = RedditCollector(client)
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["t3_7", "t3_8"]
    assert all(p.source.kind is SourceKind.REDDIT for p in posts)


@pytest.mark.asyncio
async def test_read_dedups_same_subreddit() -> None:
    client = FakeRedditClient(submissions=[_submission("7")])
    collector = RedditCollector(client)
    refs = [
        SourceRef(SourceKind.REDDIT, "r/CryptoCurrency"),
        SourceRef(SourceKind.REDDIT, "cryptocurrency"),
    ]
    _ = [p async for p in collector.read(refs, since=None)]
    assert client.fetch_calls == 1  # read once despite two equivalent refs


@pytest.mark.asyncio
async def test_read_filters_submissions_older_than_since() -> None:
    since = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    old = _submission("old", when=since - timedelta(hours=1))
    new = _submission("new", when=since + timedelta(hours=1))
    collector = RedditCollector(FakeRedditClient(submissions=[new, old]))
    posts = [p async for p in collector.read([_REF], since=since)]
    assert [p.external_id for p in posts] == ["t3_new"]


@pytest.mark.asyncio
async def test_read_empty_when_no_submissions() -> None:
    collector = RedditCollector(FakeRedditClient(submissions=[]))
    posts = [p async for p in collector.read([_REF], since=None)]
    assert posts == []


# ---------------------------------------------------------------------------
# rate limiting (no read budget — Reddit is free)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_rate_limit_sleeps_and_retries_once() -> None:
    client = FakeRedditClient(
        submissions=[_submission("7")],
        fetch_raises=[RedditRateLimitError("429", retry_after_seconds=5), None],
    )
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    collector = RedditCollector(client, sleep=fake_sleep)
    posts = [p async for p in collector.read([_REF], since=None)]
    assert [p.external_id for p in posts] == ["t3_7"]
    assert slept == [5]
    assert client.fetch_calls == 2


@pytest.mark.asyncio
async def test_long_rate_limit_skips_ref() -> None:
    client = FakeRedditClient(fetch_raises=[RedditRateLimitError("429", retry_after_seconds=600)])
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    collector = RedditCollector(client, sleep=fake_sleep)
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]
    assert slept == []  # never slept the long reset inline


@pytest.mark.asyncio
async def test_read_skips_ref_on_api_error_not_crash() -> None:
    # A non-rate-limit API error must surface as SourceUnavailableError (per-ref
    # skip the collect tick catches), NEVER the raw RedditAPIError.
    client = FakeRedditClient(fetch_raises=[RedditAPIError("500 boom")])
    collector = RedditCollector(client)
    with pytest.raises(SourceUnavailableError):
        _ = [p async for p in collector.read([_REF], since=None)]


# ---------------------------------------------------------------------------
# AC3 — registry
# ---------------------------------------------------------------------------


def test_registry_has_reddit_registered() -> None:
    from collector import registry

    assert registry.is_registered(SourceKind.REDDIT) is True


def test_build_reddit_collector_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector import registry

    monkeypatch.setattr(
        "config.get_settings",
        lambda: SimpleNamespace(reddit_client_id="", reddit_client_secret="", reddit_user_agent=""),
    )
    with pytest.raises(PoolConfigError):
        registry._build_reddit_collector()


# ---------------------------------------------------------------------------
# client (httpx.MockTransport — no network)
# ---------------------------------------------------------------------------

_TOKEN_PATH = "/api/v1/access_token"


def _client_with(
    api_handler: object, *, now: object = None, token_status: int = 200
) -> RedditHTTPClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _TOKEN_PATH:
            # Reddit REQUIRES a User-Agent even on the token request.
            assert request.headers["User-Agent"] == "ua"
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "denied"})
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return api_handler(request)  # type: ignore[operator]

    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    return RedditHTTPClient(
        client_id="cid",
        client_secret="sec",
        user_agent="ua",
        api_base_url="https://oauth.reddit.com",
        token_url=f"https://www.reddit.com{_TOKEN_PATH}",
        client=ac,
        now=now,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_client_subreddit_exists_parses_about() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.headers["User-Agent"] == "ua"
        return httpx.Response(200, json={"kind": "t5", "data": {"display_name": "cryptocurrency"}})

    client = _client_with(handler)
    assert await client.subreddit_exists("cryptocurrency") is True
    await client.aclose()


@pytest.mark.asyncio
async def test_client_subreddit_about_404_returns_false() -> None:
    client = _client_with(lambda req: httpx.Response(404, json={}))
    assert await client.subreddit_exists("ghostsub") is False
    await client.aclose()


@pytest.mark.asyncio
async def test_client_subreddit_about_403_returns_false() -> None:
    client = _client_with(lambda req: httpx.Response(403, json={}))
    assert await client.subreddit_exists("privatesub") is False
    await client.aclose()


@pytest.mark.asyncio
async def test_client_429_raises_rate_limit() -> None:
    client = _client_with(lambda req: httpx.Response(429, headers={"x-ratelimit-reset": "7"}))
    with pytest.raises(RedditRateLimitError):
        await client.subreddit_exists("cryptocurrency")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_fetch_new_parses_listing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "kind": "Listing",
                "data": {
                    "children": [
                        {
                            "kind": "t3",
                            "data": {
                                "id": "abc",
                                "name": "t3_abc",
                                "title": "hello",
                                "selftext": "world",
                                "created_utc": 1_780_000_000,
                                "author": "u1",
                                "score": 12,
                                "num_crossposts": 3,
                                "num_comments": 9,
                                "upvote_ratio": 0.87,
                                "total_awards_received": 1,
                            },
                        }
                    ],
                    "after": None,
                },
            },
        )

    client = _client_with(handler)
    subs = await client.fetch_new("cryptocurrency", limit=10)
    assert len(subs) == 1
    assert subs[0].external_id == "t3_abc"
    assert subs[0].title == "hello"
    assert subs[0].author == "u1"
    assert subs[0].score == 12
    assert subs[0].num_crossposts == 3
    assert subs[0].created_utc == datetime.fromtimestamp(1_780_000_000, tz=UTC)
    await client.aclose()


@pytest.mark.asyncio
async def test_client_server_error_raises_api_error() -> None:
    client = _client_with(lambda req: httpx.Response(500, json={}))
    with pytest.raises(RedditAPIError):
        await client.fetch_new("cryptocurrency", limit=10)
    await client.aclose()


@pytest.mark.asyncio
async def test_client_malformed_json_raises_api_error() -> None:
    client = _client_with(lambda req: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(RedditAPIError):
        await client.subreddit_exists("cryptocurrency")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_token_failure_raises_auth_error() -> None:
    client = _client_with(lambda req: httpx.Response(200, json={}), token_status=403)
    with pytest.raises(RedditAuthError):
        await client.subreddit_exists("cryptocurrency")
    await client.aclose()


@pytest.mark.asyncio
async def test_client_refreshes_token_on_401_then_succeeds() -> None:
    state = {"about_calls": 0, "token_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _TOKEN_PATH:
            state["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        state["about_calls"] += 1
        if state["about_calls"] == 1:
            return httpx.Response(401, json={})  # token rejected once
        return httpx.Response(200, json={"data": {"display_name": "x"}})

    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    client = RedditHTTPClient(
        client_id="cid",
        client_secret="sec",
        user_agent="ua",
        api_base_url="https://oauth.reddit.com",
        token_url=f"https://www.reddit.com{_TOKEN_PATH}",
        client=ac,
    )
    assert await client.subreddit_exists("x") is True
    assert state["about_calls"] == 2  # retried after refresh
    assert state["token_calls"] == 2  # token re-fetched on 401
    await client.aclose()


@pytest.mark.asyncio
async def test_client_caches_token_across_calls() -> None:
    state = {"token_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _TOKEN_PATH:
            state["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"display_name": "x"}})

    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    client = RedditHTTPClient(
        client_id="cid",
        client_secret="sec",
        user_agent="ua",
        api_base_url="https://oauth.reddit.com",
        token_url=f"https://www.reddit.com{_TOKEN_PATH}",
        client=ac,
    )
    await client.subreddit_exists("a")
    await client.subreddit_exists("b")
    assert state["token_calls"] == 1  # token fetched once, then cached
    await client.aclose()


@pytest.mark.asyncio
async def test_client_refetches_token_after_expiry() -> None:
    state = {"token_calls": 0}
    clock = {"t": datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == _TOKEN_PATH:
            state["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"data": {"display_name": "x"}})

    transport = httpx.MockTransport(handler)
    ac = httpx.AsyncClient(transport=transport)
    client = RedditHTTPClient(
        client_id="cid",
        client_secret="sec",
        user_agent="ua",
        api_base_url="https://oauth.reddit.com",
        token_url=f"https://www.reddit.com{_TOKEN_PATH}",
        client=ac,
        now=lambda: clock["t"],
    )
    await client.subreddit_exists("a")
    assert state["token_calls"] == 1
    clock["t"] = clock["t"] + timedelta(seconds=3601)  # past expiry
    await client.subreddit_exists("b")
    assert state["token_calls"] == 2  # refreshed after expiry
    await client.aclose()
