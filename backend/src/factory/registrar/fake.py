"""Deterministic in-memory `TelegramRegistrar` (TASK-133, CI-safe, no network).

Returns a fixed session + user id, and awaits `code_cb` once so the buy → poll →
register flow is exercised end-to-end in tests without touching Telegram.
"""

from __future__ import annotations

from typing import Final

from factory.registrar.base import CodeCallback, RegisteredSession

# Deterministic fixtures (named — no magic literals in the impl).
FAKE_SESSION_STRING: Final = "fake-string-session"
FAKE_TG_USER_ID: Final = 1000000001


class FakeRegistrar:
    """A scripted `TelegramRegistrar` for tests (structurally satisfies the Protocol)."""

    async def register(
        self, *, phone: str, code_cb: CodeCallback, proxy: str | None = None
    ) -> RegisteredSession:
        # Exercise the code-delivery seam so the full flow is realistic for TASK-134.
        await code_cb()
        return RegisteredSession(session_string=FAKE_SESSION_STRING, tg_user_id=FAKE_TG_USER_ID)
