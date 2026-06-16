"""TASK-114 — QR-login core service (no network, no real telethon).

Every Acceptance Criterion is encoded with a FAKE Telethon client and a FAKE
`QRLogin`, plus a controllable clock so expiry/reaping is deterministic. The
module must import with telethon absent (lazy import inside methods only).
"""

import asyncio
import builtins
import importlib
import logging
import sys

import pytest

from collector.constants import MAX_CONCURRENT_QR_LOGINS
from collector.errors import (
    CollectorError,
    QRLoginCapacityError,
    QRLoginError,
    QRLoginNotConfiguredError,
)
from collector.telegram.qr_login import (
    QRLoginIdentity,
    QRLoginService,
    QRLoginStatus,
)


class _Clock:
    """Manually advanced wall clock (epoch seconds) for deterministic expiry tests."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _FakeSessionPasswordNeededError(Exception):
    """Stand-in for telethon's SessionPasswordNeededError (2FA accounts)."""


class _FakeTelethonError(Exception):
    """A generic telethon failure whose MESSAGE must never leak into a reason."""


class _FakeQRLogin:
    """Fake of telethon's QRLogin: exposes `url` and an awaitable `wait()`.

    `wait()` resolves to whatever `wait_result` is, or raises `wait_raises`.
    """

    def __init__(
        self,
        *,
        url: str = "tg://login?token=ZmFrZS10b2tlbg",
        wait_result: bool = True,
        wait_raises: Exception | None = None,
    ) -> None:
        self.url = url
        self._wait_result = wait_result
        self._wait_raises = wait_raises
        self.wait_calls = 0

    async def wait(self) -> bool:
        self.wait_calls += 1
        if self._wait_raises is not None:
            raise self._wait_raises
        return self._wait_result


class _FakeClient:
    """Fake Telethon client driving qr_login(); records connect/disconnect."""

    def __init__(
        self,
        *,
        qr: _FakeQRLogin,
        authorized: bool = True,
        session_string: str = "SECRET-SESSION-STRING",
        identity: "QRLoginIdentity | None" = None,
        get_me_raises: Exception | None = None,
    ) -> None:
        self._qr = qr
        self._authorized = authorized
        self._session_string = session_string
        self._identity = (
            identity
            if identity is not None
            else QRLoginIdentity(tg_user_id=777_001, display_label="@alice")
        )
        self._get_me_raises = get_me_raises
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.connected = False

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def qr_login(self) -> _FakeQRLogin:
        return self._qr

    async def is_user_authorized(self) -> bool:
        return self._authorized

    def save_session(self) -> str:
        return self._session_string

    async def get_me(self) -> "QRLoginIdentity":
        if self._get_me_raises is not None:
            raise self._get_me_raises
        return self._identity


def _service(
    *,
    client: _FakeClient,
    clock: _Clock,
    timeout_seconds: int = 300,
) -> QRLoginService:
    """Build a service whose factory always yields the given fake client."""

    def factory() -> _FakeClient:
        return client

    return QRLoginService(
        client_factory=factory,
        session_password_needed_error=_FakeSessionPasswordNeededError,
        timeout_seconds=timeout_seconds,
        now=clock,
    )


# --- AC6: lazy import -------------------------------------------------------


def test_module_imports_without_telethon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing qr_login must succeed even when telethon is absent (lazy import)."""
    real_import = builtins.__import__

    def _blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "telethon" or name.startswith("telethon."):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    # Drop any cached telethon + the target module so the import is re-evaluated.
    for mod_name in list(sys.modules):
        if mod_name == "telethon" or mod_name.startswith("telethon."):
            monkeypatch.delitem(sys.modules, mod_name, raising=False)
    monkeypatch.delitem(sys.modules, "collector.telegram.qr_login", raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    mod = importlib.import_module("collector.telegram.qr_login")
    assert mod.QRLoginService is not None
    assert "telethon" not in sys.modules


def test_default_factory_is_lazy() -> None:
    """The default real factory must not be built/telethon imported at construction."""
    # Build with explicit api creds via the production constructor; the QR client is
    # only built when the factory is actually CALLED (inside start()), not here.
    svc = QRLoginService.from_settings_values(
        api_id=123,
        api_hash="hash",
        timeout_seconds=300,
    )
    assert isinstance(svc, QRLoginService)


# --- AC1: start() -----------------------------------------------------------


async def test_start_returns_token_url_and_expiry() -> None:
    clock = _Clock()
    qr = _FakeQRLogin(url="tg://login?token=ABC")
    client = _FakeClient(qr=qr)
    svc = _service(client=client, clock=clock, timeout_seconds=300)

    started = await svc.start()

    assert started.token  # non-empty opaque token
    assert started.qr_url.startswith("tg://login?token=")
    assert started.expires_at == pytest.approx(clock() + 300)
    assert client.connect_calls == 1


async def test_start_without_creds_raises_not_configured() -> None:
    clock = _Clock()

    def factory() -> _FakeClient:  # pragma: no cover - must not be called
        raise AssertionError("factory must not run when creds are missing")

    svc = QRLoginService.from_settings_values(
        api_id=None,
        api_hash=None,
        timeout_seconds=300,
        now=clock,
    )
    with pytest.raises(QRLoginNotConfiguredError):
        await svc.start()
    assert isinstance(QRLoginNotConfiguredError(), QRLoginError)
    assert isinstance(QRLoginNotConfiguredError(), CollectorError)


# --- AC3: pending -----------------------------------------------------------


async def test_poll_pending_when_not_yet_scanned() -> None:
    clock = _Clock()
    # wait() would resolve, but the service polls with a non-blocking check: model
    # "not scanned yet" as wait() not having completed → still authorized False.
    qr = _FakeQRLogin(wait_result=False)
    client = _FakeClient(qr=qr, authorized=False)
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.PENDING
    assert poll.session_string is None
    assert poll.expires_at == started.expires_at
    assert client.disconnect_calls == 0


# --- AC2: success -----------------------------------------------------------


async def test_poll_success_returns_session_and_evicts() -> None:
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=True)
    client = _FakeClient(qr=qr, authorized=True, session_string="THE-NEW-SESSION")
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.SUCCESS
    assert poll.session_string == "THE-NEW-SESSION"
    assert client.disconnect_calls == 1
    # evicted: a second poll for the same token is now unknown → expired
    again = await svc.poll(started.token)
    assert again.status is QRLoginStatus.EXPIRED


# --- AC4: password_needed + error reason redaction --------------------------


async def test_poll_password_needed_does_not_crash() -> None:
    clock = _Clock()
    qr = _FakeQRLogin(wait_raises=_FakeSessionPasswordNeededError("2fa enabled"))
    client = _FakeClient(qr=qr)
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.PASSWORD_NEEDED
    assert poll.reason  # human-readable, present
    assert poll.session_string is None
    assert client.disconnect_calls == 1


async def test_poll_error_reason_is_class_name_not_message() -> None:
    secret_in_message = "SECRET-SESSION-STRING and api_hash=topsecret"
    clock = _Clock()
    qr = _FakeQRLogin(wait_raises=_FakeTelethonError(secret_in_message))
    client = _FakeClient(qr=qr, session_string="SECRET-SESSION-STRING")
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.ERROR
    assert poll.reason == "_FakeTelethonError"  # class name only
    assert "SECRET" not in (poll.reason or "")
    assert "topsecret" not in (poll.reason or "")
    assert client.disconnect_calls == 1


# --- AC5: expiry / unknown token --------------------------------------------


async def test_poll_unknown_token_is_expired() -> None:
    clock = _Clock()
    client = _FakeClient(qr=_FakeQRLogin())
    svc = _service(client=client, clock=clock)

    poll = await svc.poll("no-such-token")
    assert poll.status is QRLoginStatus.EXPIRED
    assert poll.session_string is None


async def test_poll_past_expiry_disconnects_and_expires() -> None:
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=False)
    client = _FakeClient(qr=qr, authorized=False)
    svc = _service(client=client, clock=clock, timeout_seconds=300)

    started = await svc.start()
    clock.advance(301)  # past expiry

    poll = await svc.poll(started.token)
    assert poll.status is QRLoginStatus.EXPIRED
    assert client.disconnect_calls == 1
    # the stale client was reaped → polling again is still expired, no double-DC
    again = await svc.poll(started.token)
    assert again.status is QRLoginStatus.EXPIRED
    assert client.disconnect_calls == 1


# --- cancel + reaper --------------------------------------------------------


async def test_cancel_disconnects_and_evicts() -> None:
    clock = _Clock()
    client = _FakeClient(qr=_FakeQRLogin(wait_result=False), authorized=False)
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    await svc.cancel(started.token)
    assert client.disconnect_calls == 1
    assert (await svc.poll(started.token)).status is QRLoginStatus.EXPIRED


async def test_cancel_unknown_token_is_noop() -> None:
    clock = _Clock()
    client = _FakeClient(qr=_FakeQRLogin())
    svc = _service(client=client, clock=clock)
    # must not raise
    await svc.cancel("nope")


async def test_reaper_disconnects_expired_clients_best_effort() -> None:
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=False)
    client = _FakeClient(qr=qr, authorized=False)
    svc = _service(client=client, clock=clock, timeout_seconds=300)

    started = await svc.start()
    clock.advance(301)
    reaped = await svc.reap_expired()

    assert reaped == 1
    assert client.disconnect_calls == 1
    assert (await svc.poll(started.token)).status is QRLoginStatus.EXPIRED


async def test_reaper_swallows_disconnect_errors() -> None:
    clock = _Clock()

    class _BadDisconnectClient(_FakeClient):
        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            raise _FakeTelethonError("disconnect boom")

    client = _BadDisconnectClient(qr=_FakeQRLogin(wait_result=False), authorized=False)
    svc = _service(client=client, clock=clock, timeout_seconds=300)

    started = await svc.start()
    clock.advance(301)
    # reaper must never raise even if a client disconnect fails
    reaped = await svc.reap_expired()
    assert reaped == 1
    assert (await svc.poll(started.token)).status is QRLoginStatus.EXPIRED


# --- token uniqueness / opacity ---------------------------------------------


async def test_tokens_are_unique_per_start() -> None:
    clock = _Clock()

    clients = [_FakeClient(qr=_FakeQRLogin(wait_result=False), authorized=False) for _ in range(2)]
    pool = iter(clients)

    def factory() -> _FakeClient:
        return next(pool)

    svc = QRLoginService(
        client_factory=factory,
        session_password_needed_error=_FakeSessionPasswordNeededError,
        timeout_seconds=300,
        now=clock,
    )
    a = await svc.start()
    b = await svc.start()
    assert a.token != b.token


# --- redaction: GC "Task exception was never retrieved" leak -----------------


async def test_reaping_unpolled_failed_login_does_not_leak_secret_to_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A login whose wait() raised must be drained on reap — never logged at GC.

    If a finished-with-exception wait task is dropped WITHOUT retrieving its
    exception, CPython logs "Task exception was never retrieved" with the FULL
    exception message (which can echo the session string / api_hash) at GC time,
    defeating the class-name-only redaction. Reaping must retrieve-and-discard it.
    """
    secret = "SECRET-SESSION-STRING and api_hash=topsecret"
    clock = _Clock()
    qr = _FakeQRLogin(wait_raises=_FakeTelethonError(secret))
    client = _FakeClient(qr=qr, session_string="SECRET-SESSION-STRING")
    svc = _service(client=client, clock=clock, timeout_seconds=300)

    started = await svc.start()
    # Let the background wait() task run to completion (finished WITH exception)
    # WITHOUT ever polling — this is the path that would otherwise leak at GC.
    await asyncio.sleep(0)

    with caplog.at_level(logging.DEBUG):
        clock.advance(301)  # past expiry
        reaped = await svc.reap_expired()
        # Force any undrained task to be collected; the asyncio GC hook would log here.
        del started
        import gc

        gc.collect()
        await asyncio.sleep(0)

    assert reaped == 1
    assert "SECRET-SESSION-STRING" not in caplog.text
    assert "topsecret" not in caplog.text
    assert "never retrieved" not in caplog.text
    assert client.disconnect_calls == 1


# --- DoS belt: MAX_CONCURRENT_QR_LOGINS cap ---------------------------------


async def test_start_raises_capacity_error_when_registry_full() -> None:
    """Filling the registry to the cap makes the next start() raise; reaping frees a slot."""
    clock = _Clock()
    # Each start() needs its own fake client (the factory yields them in order).
    clients = [
        _FakeClient(qr=_FakeQRLogin(wait_result=False), authorized=False)
        for _ in range(MAX_CONCURRENT_QR_LOGINS + 1)
    ]
    pool = iter(clients)

    def factory() -> _FakeClient:
        return next(pool)

    svc = QRLoginService(
        client_factory=factory,
        session_password_needed_error=_FakeSessionPasswordNeededError,
        timeout_seconds=300,
        now=clock,
    )

    started = [await svc.start() for _ in range(MAX_CONCURRENT_QR_LOGINS)]
    assert len(started) == MAX_CONCURRENT_QR_LOGINS

    # At the cap and none expired → next start() refuses with the typed error.
    with pytest.raises(QRLoginCapacityError):
        await svc.start()
    assert isinstance(QRLoginCapacityError(), QRLoginError)
    assert isinstance(QRLoginCapacityError(), CollectorError)

    # Expire the in-flight logins; start() reaps them first, then succeeds.
    clock.advance(301)
    fresh = await svc.start()
    assert fresh.token
    assert len(started)  # original tokens were minted; cap is now relieved


# --- TASK-119: identity from get_me() on the success path -------------------


async def test_poll_success_carries_identity() -> None:
    """SUCCESS surfaces the NON-SECRET tg_user_id + display_label from get_me()."""
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=True)
    client = _FakeClient(
        qr=qr,
        authorized=True,
        session_string="THE-NEW-SESSION",
        identity=QRLoginIdentity(tg_user_id=555_123, display_label="@bob"),
    )
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.SUCCESS
    assert poll.tg_user_id == 555_123
    assert poll.display_label == "@bob"
    assert poll.session_string == "THE-NEW-SESSION"


async def test_poll_session_string_never_in_repr() -> None:
    """The minted session is a secret — it must not appear in the poll's repr."""
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=True)
    secret = "1AbC-TOP-SECRET-SESSION-STRING"
    client = _FakeClient(qr=qr, authorized=True, session_string=secret)
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)
    assert poll.status is QRLoginStatus.SUCCESS
    assert secret not in repr(poll)
    assert secret == poll.session_string  # still accessible to the caller


async def test_poll_get_me_failure_is_error_status() -> None:
    """If get_me() fails after auth we must NOT hand back an unidentifiable session."""
    clock = _Clock()
    qr = _FakeQRLogin(wait_result=True)
    client = _FakeClient(
        qr=qr,
        authorized=True,
        session_string="UNIDENTIFIABLE",
        get_me_raises=_FakeTelethonError("contains UNIDENTIFIABLE secret in message"),
    )
    svc = _service(client=client, clock=clock)

    started = await svc.start()
    poll = await svc.poll(started.token)

    assert poll.status is QRLoginStatus.ERROR
    assert poll.reason == "_FakeTelethonError"  # class name only, never the message
    assert poll.session_string is None
    assert "UNIDENTIFIABLE" not in (poll.reason or "")
    assert client.disconnect_calls == 1  # evicted
