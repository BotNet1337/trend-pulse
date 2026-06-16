"""In-code collector registry: `SourceKind -> SourceCollector` (AC7, ADR-001).

Simple in-code mapping — NO plugin loading / config DSL (ADR-001 scope guard).
`TELEGRAM` resolves to a `TelegramCollector`; `TWITTER` resolves to a
`TwitterCollector` (TASK-031) when a Bearer token is configured.

Construction of each collector is LAZY (built on first `get`) so importing the
registry never requires telethon/httpx or real credentials, and so there is no
import cycle with the platform subpackages.
"""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from collector.base import SourceCollector, SourceKind
from collector.constants import POOL_MAX
from collector.errors import PoolConfigError

if TYPE_CHECKING:
    from storage.pool_session_store import StoredSession

logger = logging.getLogger(__name__)

# Factories build a collector on demand; lazy so import is side-effect free.
_FACTORIES: dict[SourceKind, Callable[[], SourceCollector]] = {}
_INSTANCES: dict[SourceKind, SourceCollector] = {}


def register(kind: SourceKind, factory: Callable[[], SourceCollector]) -> None:
    """Register a lazy factory for `kind` (idempotent: last registration wins)."""
    _FACTORIES[kind] = factory
    _INSTANCES.pop(kind, None)


def is_registered(kind: SourceKind) -> bool:
    """True iff a collector is registered for `kind` (TWITTER is not — AC7)."""
    return kind in _FACTORIES


def get(kind: SourceKind) -> SourceCollector:
    """Return the (cached) collector for `kind`; raises if unregistered (AC7)."""
    if kind not in _FACTORIES:
        raise KeyError(f"no collector registered for source kind {kind.value!r}")
    if kind not in _INSTANCES:
        _INSTANCES[kind] = _FACTORIES[kind]()
    return _INSTANCES[kind]


def cached_collectors() -> list[SourceCollector]:
    """The collectors instantiated so far (for graceful shutdown — TASK-106).

    Returns only ALREADY-built instances (never triggers lazy construction), so a
    child that never collected has nothing to close.
    """
    return list(_INSTANCES.values())


def _build_telegram_collector() -> SourceCollector:
    """Build the production Telegram collector from (DB store + env) sessions (lazy).

    The session list is the UNION of env `TELEGRAM_POOL_SESSIONS` (the bootstrap floor /
    disaster-recovery path) and the active rows of the dynamic `pool_sessions` store
    (TASK-119), de-duped by fingerprint (the DB row wins on a conflict so its identity
    is carried). A DB read failure FAILS OPEN to env-only (logged) so a DB outage
    degrades to today's static behaviour instead of crashing pool boot.
    """
    from collector.telegram.account_pool import AccountPool, session_fingerprint
    from collector.telegram.client import build_telethon_client
    from collector.telegram.reader import TelegramCollector
    from config import get_settings, telegram_pool_sessions
    from storage.redis_client import get_redis_client

    settings = get_settings()
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise PoolConfigError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required")
    factory = build_telethon_client(
        api_id=settings.telegram_api_id, api_hash=settings.telegram_api_hash
    )
    # One Redis client, shared by the pool (persistent quarantine, TASK-102) and the
    # collector (pool-health self-observation, TASK-035; revive-signal, TASK-119).
    redis = get_redis_client()

    sessions, tg_user_ids, display_labels = _union_pool_sessions(
        env_sessions=telegram_pool_sessions(settings),
        fingerprint=session_fingerprint,
    )
    pool = AccountPool.from_sessions(
        sessions=sessions,
        factory=factory,
        redis=redis,
        tg_user_ids=tg_user_ids,
        display_labels=display_labels,
    )
    return TelegramCollector(pool, settings=settings, redis=redis)


def _union_pool_sessions(
    *,
    env_sessions: list[str],
    fingerprint: Callable[[str], str],
) -> tuple[list[str], list[int | None], list[str | None]]:
    """Union env sessions with the active DB-store sessions, de-duped by fingerprint.

    The DB store WINS on a fingerprint conflict (its identity `tg_user_id` is carried).
    Returns positional `(sessions, tg_user_ids, display_labels)` for
    `AccountPool.from_sessions` (the non-secret `display_label` labels each health row,
    TASK-120; env slots carry None). Reads
    the store via a short-lived session; FAILS OPEN to env-only on ANY error (the worker
    must boot even if the DB is briefly unreachable — disaster-recovery floor).

    JOINT `POOL_MAX` cap (TASK-119 fix): the de-duped union is TRUNCATED to `POOL_MAX`
    so the list handed to `from_sessions` can never exceed the bound and raise
    `PoolConfigError` (which would stop ingest entirely). PRECEDENCE — DB store sessions
    are kept FIRST (they carry the live, identity-keyed, revivable slots that are the
    dynamic source of truth), then env-floor sessions fill any remaining slots up to
    `POOL_MAX`. This preserves the most-functional working pool: the live DB slots are
    never starved by an over-provisioned env floor, while env still backstops a partial
    DB. The store's ADD cap (effective `POOL_MAX - env_floor_size`) keeps the DB rows
    alone within budget, so the truncation drops env-floor (not DB) slots in practice.
    """
    sessions: list[str] = []
    tg_user_ids: list[int | None] = []
    display_labels: list[str | None] = []
    seen: set[str] = set()

    db_sessions = _load_db_store_sessions()
    for stored in db_sessions:
        fp = stored.fingerprint or fingerprint(stored.session_string)
        if fp in seen:
            continue
        seen.add(fp)
        sessions.append(stored.session_string)
        tg_user_ids.append(stored.tg_user_id)
        display_labels.append(stored.display_label or None)

    for raw in env_sessions:
        fp = fingerprint(raw)
        if fp in seen:
            continue
        seen.add(fp)
        sessions.append(raw)
        tg_user_ids.append(None)
        display_labels.append(None)

    if len(sessions) > POOL_MAX:
        # DB-first truncation: keep the live identity-keyed slots, drop the overflow
        # (env floor first, by append order) so `from_sessions` never raises on size.
        logger.warning(
            "unioned pool (%d) exceeds POOL_MAX=%d; truncating to the cap (DB-first)",
            len(sessions),
            POOL_MAX,
        )
        sessions = sessions[:POOL_MAX]
        tg_user_ids = tg_user_ids[:POOL_MAX]
        display_labels = display_labels[:POOL_MAX]

    return sessions, tg_user_ids, display_labels


def _load_db_store_sessions() -> list["StoredSession"]:
    """Read active dynamic-store sessions; fail-open to [] on any error (TASK-119)."""
    try:
        from storage.database import get_session
        from storage.pool_session_store import active_sessions

        with get_session() as db:
            return active_sessions(db)
    except Exception:
        # FAIL OPEN: a DB outage must degrade to env-only, never crash pool boot.
        logger.warning("could not load dynamic pool sessions from DB; env-only pool")
        return []


def _build_twitter_collector() -> SourceCollector:
    """Build the production Twitter collector from env settings (lazy, TASK-031)."""
    from collector.twitter.client import build_twitter_client
    from collector.twitter.reader import TwitterCollector
    from config import get_settings
    from storage.redis_client import get_redis_client

    settings = get_settings()
    if not settings.twitter_bearer_token:
        raise PoolConfigError("TWITTER_BEARER_TOKEN is required for the Twitter source")
    client = build_twitter_client(
        bearer_token=settings.twitter_bearer_token,
        base_url=settings.twitter_api_base_url,
    )
    # settings + redis enable the read-budget counter + ops self-alert (best-effort).
    return TwitterCollector(client, settings=settings, redis=get_redis_client())


def _build_reddit_collector() -> SourceCollector:
    """Build the production Reddit collector from env settings (lazy, TASK-092)."""
    from collector.constants import REDDIT_OAUTH_TOKEN_PATH
    from collector.reddit.client import build_reddit_client
    from collector.reddit.reader import RedditCollector
    from config import get_settings

    settings = get_settings()
    if not (
        settings.reddit_client_id and settings.reddit_client_secret and settings.reddit_user_agent
    ):
        raise PoolConfigError(
            "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT "
            "are required for the Reddit source"
        )
    token_url = f"{settings.reddit_oauth_base_url.rstrip('/')}{REDDIT_OAUTH_TOKEN_PATH}"
    client = build_reddit_client(
        client_id=settings.reddit_client_id,
        client_secret=settings.reddit_client_secret,
        user_agent=settings.reddit_user_agent,
        api_base_url=settings.reddit_api_base_url,
        token_url=token_url,
    )
    # Reddit is FREE (no read budget) — no redis/settings needed by the collector.
    return RedditCollector(client)


# TELEGRAM + TWITTER + REDDIT registered (ADR-001). TWITTER/REDDIT stay no-ops until
# their credentials are configured: `get(kind)` raises PoolConfigError (caught by the
# tick as "unconfigured" — warn-once no-op), exactly like an empty Telegram pool.
register(SourceKind.TELEGRAM, _build_telegram_collector)
register(SourceKind.TWITTER, _build_twitter_collector)
register(SourceKind.REDDIT, _build_reddit_collector)
