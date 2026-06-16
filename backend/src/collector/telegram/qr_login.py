"""Telethon QR-login core service + in-process registry (TASK-114).

Drives Telethon `client.qr_login()` to completion and exports a NEW StringSession,
behind a typed service. State for in-progress logins lives in a module-private,
in-process registry keyed by an opaque token (the API is a single uvicorn worker
and a live `QRLogin` cannot be serialized to Redis — epic invariant).

Design rules (mirrors `collector/telegram/client.py` + `account_pool.py`):
  * telethon is NEVER imported at module load. `from_settings_values` imports the
    `SessionPasswordNeededError` class at construction time; the client factory
    imports `TelegramClient`/`StringSession` only on the first `start()`. So
    importing this module in a pure-unit context (telethon absent) must succeed.
  * `poll()` RETURNS a typed `QRLoginPoll` status for every normal terminal state
    (pending/success/expired/password_needed/error). It RAISES only for
    misconfiguration (`QRLoginNotConfiguredError`).
  * Secrets — the minted session string, api_hash, api_id — NEVER appear in logs or
    in any error `reason`. A telethon failure's reason is the exception CLASS NAME,
    never its message (which may echo a token).
  * Injectable client factory + clock so tests need no network (mirrors
    `AccountPool._now`). The token is `secrets.token_urlsafe`.
  * The minted session NEVER touches the live pool — `start()` always builds a
    brand-new client over an EMPTY StringSession.
"""

import asyncio
import logging
import secrets
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Protocol, cast

from collector.constants import MAX_CONCURRENT_QR_LOGINS
from collector.errors import QRLoginCapacityError, QRLoginNotConfiguredError

logger = logging.getLogger(__name__)

# Opaque-token entropy (bytes) for `secrets.token_urlsafe` — 32 bytes = 256 bits,
# unguessable; a token is the only handle the API holds to an in-progress login.
_TOKEN_NBYTES = 32


class QRLoginProtocol(Protocol):
    """The minimal Telethon `QRLogin` surface the service uses.

    `url` is the `tg://login?token=...` deep link rendered as a QR; `wait()` blocks
    until the QR is scanned + the login authorizes (or times out / raises)."""

    url: str

    def wait(self) -> Coroutine[object, object, bool]: ...


@dataclass(frozen=True)
class QRLoginIdentity:
    """The NON-SECRET Telegram account identity from `get_me()` (TASK-119).

    `tg_user_id` is the account's stable Telegram id (the revive/add upsert key);
    `display_label` is a non-secret masked id / `@username` for the UI. Neither is a
    secret — the session string is the only secret and lives elsewhere."""

    tg_user_id: int
    display_label: str


class QRLoginClientProtocol(Protocol):
    """The minimal Telethon client surface for QR login (no network in tests).

    A fresh client over an EMPTY StringSession: connect, drive `qr_login()`, then on
    success `save_session()` returns the NEW authorized StringSession.save() and
    `get_me()` yields the NON-SECRET account identity (TASK-119)."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def qr_login(self) -> QRLoginProtocol: ...

    async def is_user_authorized(self) -> bool: ...

    def save_session(self) -> str: ...

    async def get_me(self) -> QRLoginIdentity: ...


# A factory builds a fresh, disconnected QR-login client (empty session). No args:
# the api creds are captured in the factory closure (mirrors `build_telethon_client`).
QRLoginClientFactory = Callable[[], QRLoginClientProtocol]


class QRLoginStatus(Enum):
    """Terminal/intermediate states a `poll(token)` can report."""

    PENDING = "pending"
    SUCCESS = "success"
    EXPIRED = "expired"
    PASSWORD_NEEDED = "password_needed"
    ERROR = "error"


@dataclass(frozen=True)
class QRLoginStarted:
    """Result of `start()`: the opaque token + the QR deep link + wall expiry."""

    token: str
    qr_url: str
    expires_at: float  # epoch seconds


@dataclass(frozen=True)
class QRLoginPoll:
    """Result of `poll(token)` — never raises for normal terminal states.

    `session_string` is set only on SUCCESS; `reason` is a NON-SECRET human string
    on PASSWORD_NEEDED (why 2FA isn't supported) or ERROR (the exception class name).
    """

    status: QRLoginStatus
    expires_at: float
    # repr=False: the minted session is a secret — keep it out of any `repr()` /
    # log line / traceback frame dump while preserving equality + normal access.
    session_string: str | None = field(default=None, repr=False)
    reason: str | None = None
    # NON-SECRET account identity from `get_me()`, set only on SUCCESS (TASK-119):
    # `tg_user_id` is the revive/add upsert key and `display_label` is a masked id /
    # `@username` for the UI. Both are safe to log/return; the secret is the session.
    tg_user_id: int | None = None
    display_label: str | None = None


@dataclass
class _PendingLogin:
    """One in-progress login held in the registry (mutable bookkeeping).

    Holds the live client, the driving `wait()` task, and BOTH a wall-clock
    `expires_at` (returned to the API) and a monotonic-free epoch deadline for the
    reaper. The session string is never stored here — it is read from the client
    only at the moment of success and handed straight to the caller."""

    client: QRLoginClientProtocol
    wait_task: "asyncio.Task[bool]"
    expires_at: float


def build_qr_login_client(*, api_id: int, api_hash: str) -> QRLoginClientFactory:
    """Return a factory that builds a real Telethon client over an EMPTY session.

    telethon is imported lazily inside so importing this module never requires
    telethon (mirrors `build_telethon_client`). The client wraps `save()` so the
    protocol's `save_session()` returns the authorized StringSession string."""

    def _factory() -> QRLoginClientProtocol:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        # EMPTY StringSession → a brand-new session that never touches the pool.
        # telethon is untyped (mypy override) → the constructor is `Any`; pin both the
        # raw client and its session to structural protocols at this single boundary
        # (mirrors `build_telethon_client`) instead of leaking `Any` / `# type: ignore`.
        raw_client = cast(_RawTelethonClient, TelegramClient(StringSession(), api_id, api_hash))
        return _RealClientAdapter(raw_client)

    return _factory


class _RawSession(Protocol):
    """The single telethon `StringSession` method we need: `save()` → the new string."""

    def save(self) -> str: ...


class _RawTelethonUser(Protocol):
    """The minimal telethon `User` surface from `get_me()` (no stubs ship).

    `id` is the account's Telegram id (the non-secret upsert key); `username` is the
    optional `@handle`. Neither is a secret — the session string is."""

    id: int
    username: str | None


class _RawTelethonClient(Protocol):
    """Structural view of the real telethon client (no stubs ship) for QR login.

    `.session.save()` returns the authorized StringSession string after a successful
    `qr_login()`/`wait()` — that is the NEW session we export (never the pool's).
    `get_me()` yields the authorized account's `User` (its non-secret identity)."""

    session: _RawSession

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def qr_login(self) -> QRLoginProtocol: ...

    async def is_user_authorized(self) -> bool: ...

    async def get_me(self) -> _RawTelethonUser: ...


class _RealClientAdapter:
    """Adapts a real Telethon client to `QRLoginClientProtocol` (single typed seam).

    The raw client is pinned to `_RawTelethonClient` via one `cast` in the factory, so
    no `Any` and no `# type: ignore` leak past this boundary; `save_session()` exposes
    `StringSession.save()` of the authorized client."""

    def __init__(self, client: _RawTelethonClient) -> None:
        self._client = client

    async def connect(self) -> None:
        await self._client.connect()

    async def disconnect(self) -> None:
        await self._client.disconnect()

    async def qr_login(self) -> QRLoginProtocol:
        return await self._client.qr_login()

    async def is_user_authorized(self) -> bool:
        return await self._client.is_user_authorized()

    def save_session(self) -> str:
        return self._client.session.save()

    async def get_me(self) -> QRLoginIdentity:
        me = await self._client.get_me()
        return QRLoginIdentity(tg_user_id=me.id, display_label=_mask_label(me.id, me.username))


def _mask_label(tg_user_id: int, username: str | None) -> str:
    """Build a NON-SECRET display label from the account identity (TASK-119).

    Prefers `@username` when present (already public); otherwise a masked id that
    shows only the last 4 digits (`id:•••1234`) so the UI can disambiguate accounts
    without exposing the full id. Never includes the session string."""
    if username:
        return f"@{username}"
    tail = str(tg_user_id)[-4:]
    return f"id:***{tail}"


class QRLoginService:
    """Mint a NEW StringSession by driving Telethon `qr_login()` (TASK-114).

    `start()` builds a fresh client, connects, calls `qr_login()`, registers the live
    login under an opaque token, and returns `(token, qr_url, expires_at)`.
    `poll(token)` reports pending/success/expired/password_needed/error.
    `cancel(token)` and `reap_expired()` disconnect + drop stale clients best-effort.
    """

    _client_factory: QRLoginClientFactory
    _session_password_needed_error: type[BaseException]
    _timeout_seconds: int
    _now: Callable[[], float]
    _registry: dict[str, _PendingLogin]

    def __init__(
        self,
        *,
        client_factory: QRLoginClientFactory,
        session_password_needed_error: type[BaseException],
        timeout_seconds: int,
        now: Callable[[], float] = time,
    ) -> None:
        self._client_factory = client_factory
        self._session_password_needed_error = session_password_needed_error
        self._timeout_seconds = timeout_seconds
        self._now = now
        self._registry = {}

    @classmethod
    def from_settings_values(
        cls,
        *,
        api_id: int | None,
        api_hash: str | None,
        timeout_seconds: int,
        now: Callable[[], float] = time,
    ) -> "QRLoginService":
        """Build the production service from config values (telethon imported lazily).

        Creds may be None (app boots without QR-login configured, like an empty pool);
        the missing-creds check happens in `start()` so the service is constructable
        and the API can surface a clear 503 on first use. The real telethon
        `SessionPasswordNeededError` is imported lazily here, not at module load."""

        def _factory() -> QRLoginClientProtocol:
            if api_id is None or api_hash is None:
                raise QRLoginNotConfiguredError(
                    "QR-login requires telegram_api_id and telegram_api_hash"
                )
            return build_qr_login_client(api_id=api_id, api_hash=api_hash)()

        from telethon.errors import SessionPasswordNeededError

        return cls(
            client_factory=_factory,
            session_password_needed_error=SessionPasswordNeededError,
            timeout_seconds=timeout_seconds,
            now=now,
        )

    async def start(self) -> QRLoginStarted:
        """Create a fresh client, connect, begin QR login, and register it.

        Returns the opaque token, the `tg://login?token=...` deep link, and the wall
        expiry (now + timeout). Raises `QRLoginNotConfiguredError` (via the factory)
        when api creds are missing, or `QRLoginCapacityError` when the registry is at
        `MAX_CONCURRENT_QR_LOGINS` even after reaping expired logins — the raise paths."""
        # DoS belt: bound the in-process registry. Reap first (an abandoned/expired
        # login frees a slot), then refuse only if live logins still saturate the cap.
        if len(self._registry) >= MAX_CONCURRENT_QR_LOGINS:
            await self.reap_expired()
            if len(self._registry) >= MAX_CONCURRENT_QR_LOGINS:
                raise QRLoginCapacityError(
                    f"too many concurrent QR logins (cap {MAX_CONCURRENT_QR_LOGINS})"
                )

        client = self._client_factory()
        await client.connect()
        # After a successful connect the client owns a live socket. If `qr_login()` or
        # task creation raises BEFORE the entry is registered, disconnect best-effort
        # so the connected client cannot leak (the registry never sees it).
        try:
            qr = await client.qr_login()

            token = secrets.token_urlsafe(_TOKEN_NBYTES)
            expires_at = self._now() + self._timeout_seconds
            # Drive wait() in the background so `poll()` is non-blocking: a real
            # QRLogin.wait() blocks until the QR is scanned (or times out).
            wait_task: asyncio.Task[bool] = asyncio.create_task(qr.wait())
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                # Best-effort teardown of the pre-registration client — log (not
                # swallow) and re-raise the original failure below.
                logger.warning("qr-login client disconnect failed during start cleanup")
            raise

        self._registry[token] = _PendingLogin(
            client=client, wait_task=wait_task, expires_at=expires_at
        )
        return QRLoginStarted(token=token, qr_url=qr.url, expires_at=expires_at)

    async def poll(self, token: str) -> QRLoginPoll:
        """Report the current state of the login `token` (never raises for callers).

        Unknown/expired tokens return EXPIRED (never KeyError). On a terminal state
        the client is disconnected and the entry evicted. Secrets never appear in
        `reason` — a telethon failure's reason is its exception class name."""
        pending = self._registry.get(token)
        if pending is None:
            return QRLoginPoll(status=QRLoginStatus.EXPIRED, expires_at=self._now())

        if self._now() >= pending.expires_at:
            await self._evict(token, pending)
            return QRLoginPoll(status=QRLoginStatus.EXPIRED, expires_at=pending.expires_at)

        # Give the background `wait()` task a chance to progress (it may have already
        # resolved) without blocking on a real, long-running scan: yield one loop
        # turn, then read its state non-blockingly.
        if not pending.wait_task.done():
            await asyncio.sleep(0)
        if not pending.wait_task.done():
            return QRLoginPoll(status=QRLoginStatus.PENDING, expires_at=pending.expires_at)

        error = pending.wait_task.exception()
        if error is not None:
            return await self._resolve_error(token, pending, error)

        authorized = pending.wait_task.result()
        if not authorized or not await pending.client.is_user_authorized():
            # wait() resolved falsy (token rotated / not yet authorized) — still
            # pending until expiry; don't evict.
            return QRLoginPoll(status=QRLoginStatus.PENDING, expires_at=pending.expires_at)

        # Learn the NON-SECRET account identity BEFORE evicting (the client is still
        # live + authorized). `get_me()` keys the revive/add upsert (TASK-119); if it
        # fails we must NOT hand back a session we cannot identity-key, so surface an
        # ERROR (class name only — never the exception message, which can echo a
        # secret). The session string is read only after a successful identity.
        try:
            identity = await pending.client.get_me()
        except Exception as exc:
            await self._evict(token, pending)
            return QRLoginPoll(
                status=QRLoginStatus.ERROR,
                expires_at=pending.expires_at,
                reason=type(exc).__name__,
            )
        session_string = pending.client.save_session()
        await self._evict(token, pending)
        return QRLoginPoll(
            status=QRLoginStatus.SUCCESS,
            expires_at=pending.expires_at,
            session_string=session_string,
            tg_user_id=identity.tg_user_id,
            display_label=identity.display_label,
        )

    async def _resolve_error(
        self, token: str, pending: _PendingLogin, error: BaseException
    ) -> QRLoginPoll:
        """Map a `wait()` exception to a typed poll status; evict the client.

        2FA → PASSWORD_NEEDED (clear, non-secret reason). Any other telethon error →
        ERROR with the exception CLASS NAME as reason (never its message, which can
        echo the session string / api_hash)."""
        await self._evict(token, pending)
        if isinstance(error, self._session_password_needed_error):
            return QRLoginPoll(
                status=QRLoginStatus.PASSWORD_NEEDED,
                expires_at=pending.expires_at,
                reason="account has 2FA (cloud password) enabled — not supported in QR-only login",
            )
        # CLASS NAME ONLY — the message may contain secrets/tokens.
        return QRLoginPoll(
            status=QRLoginStatus.ERROR,
            expires_at=pending.expires_at,
            reason=type(error).__name__,
        )

    async def cancel(self, token: str) -> None:
        """Disconnect + evict a login (user navigated away / abandoned). No-op if unknown."""
        pending = self._registry.get(token)
        if pending is not None:
            await self._evict(token, pending)

    async def reap_expired(self) -> int:
        """Disconnect + drop every login past its deadline; return how many were reaped.

        Best-effort, mirrors `AccountPool.aclose`: a disconnect failure is logged, not
        raised, so one bad client can't block reaping the rest. Intended to run on a
        periodic sweep (`QR_LOGIN_REAP_INTERVAL_SECONDS`)."""
        now = self._now()
        expired = [
            (token, pending)
            for token, pending in self._registry.items()
            if now >= pending.expires_at
        ]
        for token, pending in expired:
            await self._evict(token, pending)
        return len(expired)

    async def _evict(self, token: str, pending: _PendingLogin) -> None:
        """Drain the wait task, disconnect the client (best-effort), drop the entry.

        Draining is CRITICAL for redaction: if a finished `wait()` task carries an
        exception (whose message can echo the session string / api_hash) and we drop
        it without retrieving that exception, CPython logs "Task exception was never
        retrieved" with the FULL exception at GC time — defeating the class-name-only
        redaction in `_resolve_error`. So: if the task is done and not cancelled,
        retrieve-and-discard its exception; otherwise cancel it. No eviction path may
        leave a finished-with-exception task undrained."""
        self._registry.pop(token, None)
        self._drain_wait_task(pending.wait_task)
        try:
            await pending.client.disconnect()
        except Exception:
            # Best-effort teardown — log (not swallow) so one bad client can't block
            # evicting the rest; never re-raise (mirrors AccountPool.aclose).
            logger.warning("qr-login client disconnect failed during evict")

    @staticmethod
    def _drain_wait_task(task: "asyncio.Task[bool]") -> None:
        """Drain a wait task so a finished-with-exception one can't leak at GC.

        If the task already finished (not cancelled), retrieve-and-discard its
        exception so CPython never logs "Task exception was never retrieved" with the
        raw (possibly secret-bearing) exception. If still running, cancel it. NEVER
        re-raise: the secret-bearing exception was already mapped to a class-name-only
        reason in `_resolve_error` and must not propagate out of teardown."""
        if task.done():
            if not task.cancelled():
                # Retrieve-and-discard — marks the exception as consumed (no GC log).
                _ = task.exception()
            return
        task.cancel()
