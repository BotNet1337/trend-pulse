"""In-code collector registry: `SourceKind -> SourceCollector` (AC7, ADR-001).

Simple in-code mapping — NO plugin loading / config DSL (ADR-001 scope guard).
`TELEGRAM` resolves to a `TelegramCollector`; `TWITTER` is declared in the enum as
a future marker but is deliberately NOT registered (AC7).

Construction of the Telegram collector is LAZY (built on first `get`) so importing
the registry never requires telethon or real pool credentials, and so there is no
import cycle with the telegram subpackage.
"""

from collections.abc import Callable

from collector.base import SourceCollector, SourceKind
from collector.errors import PoolConfigError

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


def _build_telegram_collector() -> SourceCollector:
    """Build the production Telegram collector from env settings (lazy)."""
    from collector.telegram.account_pool import AccountPool
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
    pool = AccountPool.from_sessions(sessions=telegram_pool_sessions(settings), factory=factory)
    # Pass settings + redis for pool health self-observation (TASK-035).
    return TelegramCollector(pool, settings=settings, redis=get_redis_client())


# TELEGRAM registered (AC7); TWITTER intentionally absent (future marker only).
register(SourceKind.TELEGRAM, _build_telegram_collector)
