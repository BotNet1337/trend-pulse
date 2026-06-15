"""Domain errors for the collector (CONVENTIONS: explicit errors, no bare except)."""


class CollectorError(Exception):
    """Base class for all collector domain errors."""


class PoolConfigError(CollectorError):
    """Account-pool misconfiguration (missing creds, size outside POOL_MIN..POOL_MAX)."""


class SourceUnavailableError(CollectorError):
    """A source could not be read (private/removed/renamed) — skip it, keep the rest."""


class AllAccountsFloodWaitError(CollectorError):
    """Every pool account is cooling down under FLOOD_WAIT; caller should back off."""


class PoolExhaustedError(CollectorError):
    """Every pool account is quarantined (dead sessions) — re-mint required (TASK-087).

    Distinct from `AllAccountsFloodWaitError`: cooling accounts recover after their
    cooldown, quarantined ones never do. The reader must NOT retry/sleep on this —
    the tick skips the ref (like SourceUnavailableError) until sessions are re-minted.
    """


class BufferWriteError(CollectorError):
    """A raw post could not be written to the Redis buffer (not silently dropped)."""


class QRLoginError(CollectorError):
    """Base for QR-login service errors (TASK-114, EPIC-TG-QR-POOL).

    The service prefers RETURNING a typed `QRLoginPoll` status for normal terminal
    states (expired/password_needed/error) and RAISES only for misconfiguration or
    programmer errors — see the subclasses below."""


class QRLoginNotConfiguredError(QRLoginError):
    """`start()` was called without `telegram_api_id`/`telegram_api_hash` configured.

    Raised (not a poll status) because it is a deployment misconfiguration: the API
    maps it to a clear 503 so the operator sets the creds — minting can't proceed."""


class QRLoginCapacityError(QRLoginError):
    """`start()` was called while the in-process registry is at `MAX_CONCURRENT_QR_LOGINS`.

    Raised (not a poll status) as a DoS belt: the registry holds live connected
    clients, so an unauthenticated `start()` flood is bounded. `start()` first reaps
    expired logins; this only fires if the cap is still saturated by live ones. The
    API maps it to a 429/503 — try again once an in-flight login finishes or expires."""


class TwitterAPIError(CollectorError):
    """A non-recoverable Twitter/X API error (non-2xx other than 404/429) — skip the ref."""


class TwitterCreditsDepletedError(CollectorError):
    """X API returned 402 CreditsDepleted — the pay-per-use account has no credits.

    A PERSISTENT billing state (not transient): every read is rejected until the
    owner tops up. The collector pauses all Twitter reads for a cooldown and alerts
    ops ONCE rather than re-failing every account every tick (TASK-031)."""


class TwitterRateLimitError(CollectorError):
    """Twitter/X API returned 429. Carries `retry_after_seconds` (from the
    `x-rate-limit-reset` header when present) so the reader can back off inline
    (short) or skip the ref (long) — mirrors the Telegram FLOOD_WAIT contract."""

    def __init__(self, message: str, *, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TwitterReadBudgetExceededError(SourceUnavailableError):
    """The monthly Twitter read budget is exhausted — stop reading (spend backstop).

    Subclasses `SourceUnavailableError` so `collect_tick` already skips the ref
    cleanly (no tasks.py change), while remaining distinguishable for the once-only
    ops alert."""


class RedditAPIError(CollectorError):
    """A non-recoverable Reddit API error (non-2xx other than 401/403/404/429) — skip the ref.

    Reddit OAuth2 application-only is FREE (no per-read cost, unlike X pay-per-use),
    so there is no credits/budget error here — only transient API/rate-limit ones
    (TASK-092)."""


class RedditAuthError(CollectorError):
    """Reddit OAuth2 token could not be obtained/refreshed (bad client creds / auth 4xx).

    The reader maps this to a per-ref `SourceUnavailableError` (skip the ref, never
    crash the tick); the credentials are owner-supplied env (TASK-092)."""


class RedditRateLimitError(CollectorError):
    """Reddit API returned 429. Carries `retry_after_seconds` (from the
    `x-ratelimit-reset`/`retry-after` header when present) so the reader can back off
    inline (short) or skip the ref (long) — mirrors the Twitter 429 contract."""

    def __init__(self, message: str, *, retry_after_seconds: float) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
