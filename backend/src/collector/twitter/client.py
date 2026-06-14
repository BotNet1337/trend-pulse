"""Typed X API v2 client + factory (TASK-031, testability — mirrors telegram/client).

The reader depends ONLY on `TwitterClientProtocol`, never on httpx — so unit tests
inject a fake client (no network) while production wires `TwitterHTTPClient`. The
Bearer token is an app-only read credential from env; it is NEVER logged.

Only the two endpoints the collector needs are implemented:
  * GET /2/users/by/username/:username        -> resolve a handle to a user id
  * GET /2/users/:id/tweets                   -> recent tweets (since `start_time`)

Errors map to the collector domain: 429 -> `TwitterRateLimitError` (carries the
reset hint), other non-2xx (except 404 on resolve -> None) -> `TwitterAPIError`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx

from collector.errors import TwitterAPIError, TwitterRateLimitError

# Tweet fields we request — keep MINIMAL (every field/tweet read costs money).
_TWEET_FIELDS = "public_metrics,created_at"
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_NOT_FOUND = 404
_HTTP_OK_FLOOR = 200
_HTTP_OK_CEIL = 300
# Conservative fallback wait when a 429 carries no parseable reset header (seconds).
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class _Tweet:
    """Concrete tweet satisfying `mapper.TwitterTweet` (structural)."""

    id: str
    text: str | None
    created_at: datetime | None
    author: str | None
    public_metrics: Mapping[str, int] = field(default_factory=dict)


class TwitterClientProtocol(Protocol):
    """Minimal X API v2 surface the reader uses (rate-limit handled by raising)."""

    async def resolve_user_id(self, username: str) -> str | None:
        """Return the numeric user id for `username`, or None if not found/public."""
        ...

    async def fetch_tweets(
        self,
        user_id: str,
        *,
        start_time: datetime | None,
        max_results: int,
        author: str | None = None,
    ) -> list[_Tweet]:
        """Return recent tweets for `user_id` newer than `start_time` (id desc)."""
        ...

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        ...


def _parse_created_at(value: object) -> datetime | None:
    """Parse an RFC3339 timestamp (X uses trailing 'Z') to tz-aware UTC, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _retry_after_from(response: httpx.Response) -> float:
    """Seconds to wait from a 429 response (`x-rate-limit-reset` epoch, else default)."""
    reset = response.headers.get("x-rate-limit-reset")
    if reset is not None:
        try:
            remaining = float(reset) - datetime.now(tz=UTC).timestamp()
        except ValueError:
            return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
        return max(remaining, 0.0)
    return _DEFAULT_RATE_LIMIT_WAIT_SECONDS


class TwitterHTTPClient:
    """Production X API v2 client over httpx with app-only Bearer auth."""

    def __init__(self, *, bearer_token: str, base_url: str, client: httpx.AsyncClient) -> None:
        # The token is held only to build the auth header; never logged.
        self._auth = {"Authorization": f"Bearer {bearer_token}"}
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def resolve_user_id(self, username: str) -> str | None:
        url = f"{self._base_url}/2/users/by/username/{username}"
        response = await self._client.get(url, headers=self._auth)
        if response.status_code == _HTTP_NOT_FOUND:
            return None
        self._raise_for_status(response, context="resolve_user_id")
        data = self._json_body(response, context="resolve_user_id").get("data")
        if not isinstance(data, dict):
            return None  # username valid-format but no public account
        user_id = data.get("id")
        return str(user_id) if user_id is not None else None

    async def fetch_tweets(
        self,
        user_id: str,
        *,
        start_time: datetime | None,
        max_results: int,
        author: str | None = None,
    ) -> list[_Tweet]:
        params: dict[str, str] = {
            "tweet.fields": _TWEET_FIELDS,
            "max_results": str(max_results),
        }
        if start_time is not None:
            params["start_time"] = start_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{self._base_url}/2/users/{user_id}/tweets"
        response = await self._client.get(url, headers=self._auth, params=params)
        self._raise_for_status(response, context="fetch_tweets")
        payload = self._json_body(response, context="fetch_tweets").get("data")
        if not isinstance(payload, list):
            return []  # no tweets in window
        return [self._to_tweet(item, author) for item in payload if isinstance(item, dict)]

    @staticmethod
    def _to_tweet(item: dict[str, object], author: str | None) -> _Tweet:
        raw_metrics = item.get("public_metrics")
        metrics: dict[str, int] = {}
        if isinstance(raw_metrics, dict):
            metrics = {k: v for k, v in raw_metrics.items() if isinstance(v, int)}
        text = item.get("text")
        return _Tweet(
            id=str(item.get("id", "")),
            text=text if isinstance(text, str) else None,
            created_at=_parse_created_at(item.get("created_at")),
            author=author,
            public_metrics=metrics,
        )

    @staticmethod
    def _json_body(response: httpx.Response, *, context: str) -> dict[str, object]:
        """Parse a 2xx JSON body to a dict; malformed/non-object → TwitterAPIError.

        A 200 with a non-JSON or non-object body (CDN/proxy error page, partial
        read) must NOT escape as a raw ValueError — it maps to the collector domain
        so the reader skips the ref instead of crashing the tick.
        """
        try:
            body = response.json()
        except ValueError as exc:
            raise TwitterAPIError(f"twitter malformed JSON ({context})") from exc
        if not isinstance(body, dict):
            raise TwitterAPIError(f"twitter unexpected JSON shape ({context})")
        return body

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, context: str) -> None:
        if _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEIL:
            return
        if response.status_code == _HTTP_TOO_MANY_REQUESTS:
            raise TwitterRateLimitError(
                f"twitter rate-limited ({context})",
                retry_after_seconds=_retry_after_from(response),
            )
        # Never include the response body — it could echo request params; status only.
        raise TwitterAPIError(f"twitter api error {response.status_code} ({context})")

    async def aclose(self) -> None:
        await self._client.aclose()


def build_twitter_client(
    *, bearer_token: str, base_url: str, timeout_seconds: float = 10.0
) -> TwitterHTTPClient:
    """Build a production `TwitterHTTPClient` (httpx). Lazy — no network at import."""
    client = httpx.AsyncClient(timeout=timeout_seconds)
    return TwitterHTTPClient(bearer_token=bearer_token, base_url=base_url, client=client)
