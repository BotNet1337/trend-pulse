"""TASK-133 follow-up — the real TelethonRegistrar must CREATE a new account.

A freshly-bought number has no Telegram account yet, so `sign_in` raises
`PhoneNumberUnoccupied` and the registrar must `sign_up`. telethon IS installed, so we
monkeypatch `telethon.TelegramClient` (the registrar imports it lazily inside
`register`, so attribute monkeypatching takes effect) and use the REAL error class.
"""

from __future__ import annotations

import telethon
from telethon.errors import PhoneNumberUnoccupiedError

from factory.constants import FACTORY_SIGNUP_FIRST_NAMES
from factory.registrar.telethon import TelethonRegistrar, pick_signup_first_name


def test_pick_signup_first_name_is_deterministic_and_in_pool() -> None:
    a = pick_signup_first_name("+79991234567")
    b = pick_signup_first_name("+79991234567")
    assert a == b  # same phone → same name (no randomness)
    assert a in FACTORY_SIGNUP_FIRST_NAMES


class _Me:
    id = 555


async def test_register_new_number_falls_through_to_sign_up(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: dict[str, object] = {"sign_in": 0, "sign_up": None}

    class _FakeClient:
        def __init__(
            self, session: object, api_id: int, api_hash: str, proxy: object = None
        ) -> None:
            self.session = session  # a real StringSession → StringSession.save() works

        async def connect(self) -> None: ...

        async def disconnect(self) -> None: ...

        async def send_code_request(self, phone: str) -> None: ...

        async def sign_in(self, phone: str, code: str) -> None:
            calls["sign_in"] = int(calls["sign_in"]) + 1  # type: ignore[arg-type]
            raise PhoneNumberUnoccupiedError(request=None)

        async def sign_up(self, code: str, first_name: str, last_name: str) -> None:
            calls["sign_up"] = (code, first_name, last_name)

        async def get_me(self) -> _Me:
            return _Me()

    monkeypatch.setattr(telethon, "TelegramClient", _FakeClient)

    async def code_cb() -> str:
        return "123456"

    registrar = TelethonRegistrar(api_id=1, api_hash="h")
    session = await registrar.register(phone="+79991234567", code_cb=code_cb)

    assert calls["sign_in"] == 1
    assert calls["sign_up"] is not None  # the NEW-account path ran
    code, first, last = calls["sign_up"]  # type: ignore[misc]
    assert code == "123456"
    assert first in FACTORY_SIGNUP_FIRST_NAMES
    assert last == ""
    assert session.tg_user_id == 555
    assert isinstance(session.session_string, str)
