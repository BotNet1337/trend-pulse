"""Typed Reddit OAuth2 client + factory (TASK-092, mirrors twitter/client).

The reader depends ONLY on `RedditClientProtocol`, never on httpx — so unit tests
inject a fake client (no network) while production wires `RedditHTTPClient`. The
client_id/secret are app-only read credentials from env; they are NEVER logged.

OAuth2 application-only (`grant_type=client_credentials`, HTTP Basic auth) yields a
short-lived bearer token from the auth host (https://www.reddit.com/api/v1/access_token);
the data API then lives on https://oauth.reddit.com. The token is cached and
refreshed on expiry (and once on a 401). Reddit REQUIRES a unique `User-Agent`.

Only the two endpoints the collector needs are implemented:
  * GET /r/{subreddit}/about     -> validate a subreddit exists / is public
  * GET /r/{subreddit}/new       -> recent submissions (newest first)

Errors map to the collector domain: 429 -> `RedditRateLimitError` (carries the
reset hint), auth failure -> `RedditAuthError`, other non-2xx -> `RedditAPIError`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from collector.constants import REDDIT_TOKEN_EXPIRY_LEEWAY_SECONDS
from collector.errors import RedditAPIError, RedditAuthError, RedditRateLimitError

_HTTP_OK_FLOOR = 200
_HTTP_OK_CEIL = 300
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
# Conservative fallback wait when a 429 carries no parseable reset header (seconds).
_DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0
_DEFAULT_TOKEN_TTL_SECONDS = 3600


@dataclass(frozen=True)
class _Submission:
    """Concrete submission satisfying `mapper.RedditSubmission` (structural)."""

    external_id: str
    title: str | None
    selftext: str | None
    created_utc: datetime | None
    author: str | None
    score: int = 0
    num_crossposts: int = 0
    num_comments: int = 0
    upvote_ratio: float = 0.0
    total_awards_received: int = 0


class RedditClientProtocol(Protocol):
    """Minimal Reddit API surface the reader uses (rate-limit handled by raising)."""

    async def subreddit_exists(self, name: str) -> bool:
        """Return True iff `name` is a readable public subreddit."""
        ...

    async def fetch_new(self, name: str, *, limit: int) -> list[_Submission]:
        """Return the newest submissions for subreddit `name` (newest first)."""
        ...

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        ...


def _parse_created_utc(value: object) -> datetime | None:
    """Parse a Reddit `created_utc` (epoch seconds, float|int) to tz-aware UTC."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _retry_after_from(response: httpx.Response) -> float:
    """Seconds to wait from a 429 (`x-ratelimit-reset` or `retry-after`, else default)."""
    for header in ("x-ratelimit-reset", "retry-after"):
        raw = response.headers.get(header)
        if raw is not None:
            try:
                return max(float(raw), 0.0)
            except ValueError:
                continue
    return _DEFAULT_RATE_LIMIT_WAIT_SECONDS


class RedditHTTPClient:
    """Production Reddit client over httpx with OAuth2 application-only auth."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        user_agent: str,
        api_base_url: str,
        token_url: str,
        client: httpx.AsyncClient,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        # Held only to build the Basic-auth for the token request; never logged.
        self._basic_auth = httpx.BasicAuth(client_id, client_secret)
        self._user_agent = user_agent
        self._api_base_url = api_base_url.rstrip("/")
        self._token_url = token_url
        self._client = client
        self._now: Callable[[], datetime] = now if now is not None else (lambda: datetime.now(UTC))
        self._token: str | None = None
        self._token_expiry_epoch = 0.0

    async def subreddit_exists(self, name: str) -> bool:
        response = await self._get(f"/r/{name}/about")
        if response.status_code in (_HTTP_FORBIDDEN, _HTTP_NOT_FOUND):
            return False  # private / banned / nonexistent
        self._raise_for_status(response, context="subreddit_about")
        data = self._json_body(response, context="subreddit_about").get("data")
        return isinstance(data, dict)

    async def fetch_new(self, name: str, *, limit: int) -> list[_Submission]:
        response = await self._get(f"/r/{name}/new", params={"limit": str(limit)})
        self._raise_for_status(response, context="subreddit_new")
        listing = self._json_body(response, context="subreddit_new").get("data")
        children = listing.get("children") if isinstance(listing, dict) else None
        if not isinstance(children, list):
            return []  # empty / unexpected shape
        result: list[_Submission] = []
        for child in children:
            if not isinstance(child, dict):
                continue
            data = child.get("data")
            if isinstance(data, dict):
                result.append(self._to_submission(data))
        return result

    # --- OAuth2 token management --------------------------------------------------

    async def _ensure_token(self) -> str:
        if self._token is not None and self._now().timestamp() < self._token_expiry_epoch:
            return self._token
        return await self._fetch_token()

    async def _fetch_token(self) -> str:
        response = await self._client.post(
            self._token_url,
            data={"grant_type": "client_credentials"},
            auth=self._basic_auth,
            headers={"User-Agent": self._user_agent},
        )
        if response.status_code == _HTTP_TOO_MANY_REQUESTS:
            raise RedditRateLimitError(
                "reddit rate-limited (token)", retry_after_seconds=_retry_after_from(response)
            )
        if not _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEIL:
            # Never echo the body — it could leak the request; status only.
            raise RedditAuthError(f"reddit token request failed ({response.status_code})")
        body = self._json_body(response, context="oauth_token")
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise RedditAuthError("reddit token response missing access_token")
        expires_in = body.get("expires_in")
        ttl = expires_in if isinstance(expires_in, (int, float)) else _DEFAULT_TOKEN_TTL_SECONDS
        self._token = token
        self._token_expiry_epoch = self._now().timestamp() + max(
            float(ttl) - REDDIT_TOKEN_EXPIRY_LEEWAY_SECONDS, 0.0
        )
        return token

    def _headers(self, token: str) -> dict[str, str]:
        # Reddit REQUIRES a unique User-Agent or it 429s/403s aggressively.
        return {"Authorization": f"Bearer {token}", "User-Agent": self._user_agent}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET on the API host with a valid token; refresh once on a 401."""
        url = f"{self._api_base_url}{path}"
        token = await self._ensure_token()
        response = await self._client.get(url, headers=self._headers(token), params=params)
        if response.status_code == _HTTP_UNAUTHORIZED:
            # Token expired/revoked between checks — refresh once and retry.
            self._token = None
            token = await self._ensure_token()
            response = await self._client.get(url, headers=self._headers(token), params=params)
        return response

    # --- parsing helpers ----------------------------------------------------------

    @staticmethod
    def _to_submission(data: dict[str, object]) -> _Submission:
        name = data.get("name")
        sid = data.get("id")
        external_id = (
            str(name) if isinstance(name, str) and name else f"t3_{sid}" if sid is not None else ""
        )
        title = data.get("title")
        selftext = data.get("selftext")
        author = data.get("author")
        return _Submission(
            external_id=external_id,
            title=title if isinstance(title, str) else None,
            selftext=selftext if isinstance(selftext, str) else None,
            created_utc=_parse_created_utc(data.get("created_utc")),
            author=author if isinstance(author, str) else None,
            score=_coerce_int(data.get("score")),
            num_crossposts=_coerce_int(data.get("num_crossposts")),
            num_comments=_coerce_int(data.get("num_comments")),
            upvote_ratio=_coerce_float(data.get("upvote_ratio")),
            total_awards_received=_coerce_int(data.get("total_awards_received")),
        )

    @staticmethod
    def _json_body(response: httpx.Response, *, context: str) -> dict[str, object]:
        """Parse a 2xx JSON body to a dict; malformed/non-object → RedditAPIError."""
        try:
            body = response.json()
        except ValueError as exc:
            raise RedditAPIError(f"reddit malformed JSON ({context})") from exc
        if not isinstance(body, dict):
            raise RedditAPIError(f"reddit unexpected JSON shape ({context})")
        return body

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, context: str) -> None:
        if _HTTP_OK_FLOOR <= response.status_code < _HTTP_OK_CEIL:
            return
        if response.status_code == _HTTP_TOO_MANY_REQUESTS:
            raise RedditRateLimitError(
                f"reddit rate-limited ({context})",
                retry_after_seconds=_retry_after_from(response),
            )
        if response.status_code == _HTTP_UNAUTHORIZED:
            raise RedditAuthError(f"reddit unauthorized ({context})")
        # Never include the response body — status only.
        raise RedditAPIError(f"reddit api error {response.status_code} ({context})")

    async def aclose(self) -> None:
        await self._client.aclose()


def _coerce_int(value: object) -> int:
    # Intentionally PERMISSIVE: preserves the raw API value (Reddit `score` can be
    # negative for downvoted posts). The non-negative PostMetrics invariant is
    # enforced LATER, by the mapper (`mapper._as_int` clamps to >= 0) — keeping the
    # DTO faithful to the API and the business rule in one place.
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _coerce_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def build_reddit_client(
    *,
    client_id: str,
    client_secret: str,
    user_agent: str,
    api_base_url: str,
    token_url: str,
    timeout_seconds: float = 10.0,
) -> RedditHTTPClient:
    """Build a production `RedditHTTPClient` (httpx). Lazy — no network at import."""
    client = httpx.AsyncClient(timeout=timeout_seconds)
    return RedditHTTPClient(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
        api_base_url=api_base_url,
        token_url=token_url,
        client=client,
    )
