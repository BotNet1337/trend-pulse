"""AC3 (behavioral, marker `integration`) — real public channel read via pool.

Skipped cleanly when env creds are absent so `make ci-fast` / CI without creds
never fails. Requires TELEGRAM_API_ID/HASH + TELEGRAM_POOL_SESSIONS (≥ POOL_MIN
technical-account StringSessions) and network egress to Telegram.
"""

import pytest

from collector.base import SourceKind, SourceRef
from collector.constants import POOL_MIN
from collector.telegram.account_pool import AccountPool
from collector.telegram.client import build_telethon_client
from collector.telegram.reader import TelegramCollector
from config import get_settings, telegram_pool_sessions

pytestmark = pytest.mark.integration

_PUBLIC_CHANNEL = "@telegram"


def _collector_or_skip() -> TelegramCollector:
    settings = get_settings()
    sessions = telegram_pool_sessions(settings)
    if (
        settings.telegram_api_id is None
        or not settings.telegram_api_hash
        or len(sessions) < POOL_MIN
    ):
        pytest.skip("telegram pool creds absent (TELEGRAM_API_ID/HASH/POOL_SESSIONS)")
    factory = build_telethon_client(
        api_id=settings.telegram_api_id, api_hash=settings.telegram_api_hash
    )
    pool = AccountPool.from_sessions(sessions=sessions, factory=factory)
    return TelegramCollector(pool)


@pytest.mark.asyncio
async def test_read_real_public_channel_yields_rawposts() -> None:
    collector = _collector_or_skip()
    ref = SourceRef(SourceKind.TELEGRAM, _PUBLIC_CHANNEL)

    posts = []
    async with collector:  # ensures pool clients are disconnected on exit
        async for post in collector.read([ref], since=None):
            posts.append(post)
            if len(posts) >= 1:
                break

    assert posts, "expected at least one RawPost from the public channel"
    first = posts[0]
    assert first.source.kind is SourceKind.TELEGRAM
    assert first.external_id
    # Normalized metrics are populated (integers, never None).
    assert first.metrics.views >= 0
    assert first.metrics.forwards >= 0
    assert first.metrics.reactions >= 0


@pytest.mark.asyncio
async def test_validate_ref_public_channel_true() -> None:
    collector = _collector_or_skip()
    async with collector:  # disconnect pool clients on exit
        assert await collector.validate_ref(SourceRef(SourceKind.TELEGRAM, _PUBLIC_CHANNEL))
