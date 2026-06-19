"""TASK-133 — FakeRegistrar unit tests (deterministic, no network)."""

from __future__ import annotations

from factory.registrar.base import RegisteredSession, TelegramRegistrar
from factory.registrar.fake import (
    FAKE_SESSION_STRING,
    FAKE_TG_USER_ID,
    FakeRegistrar,
)


def test_fake_registrar_satisfies_protocol() -> None:
    assert isinstance(FakeRegistrar(), TelegramRegistrar)


async def test_fake_registrar_returns_deterministic_session() -> None:
    called = {"n": 0}

    async def code_cb() -> str:
        called["n"] += 1
        return "123456"

    registrar = FakeRegistrar()
    session = await registrar.register(phone="+79991234567", code_cb=code_cb)
    assert session == RegisteredSession(
        session_string=FAKE_SESSION_STRING, tg_user_id=FAKE_TG_USER_ID
    )
    # The code callback is exercised so the flow is realistic for TASK-134.
    assert called["n"] == 1
