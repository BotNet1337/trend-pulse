"""Real Mobileproxy.space REST provider over httpx (TASK-139) — mirrors smspva.py.

Calls are Bearer-authed JSON requests to `{base_url}{endpoint}`. `allocate` →
buyProxy (builds a `socks5://user:pass@host:port` uri + a lease_id from the port id),
`release` → refundProxy (best-effort, never raises), `balance` → getBalance (Decimal).
Non-OK HTTP, malformed JSON, and incomplete buyProxy bodies map to typed
`ProxyProviderError` subclasses — messages name the endpoint only and NEVER echo the
body, the built proxy URI (user:pass creds), or the api token (Bearer secret).

The exact wire format is partly unverified publicly (confirmed on the free 2h trial
at the final gate); every route/field is a NAMED CONSTANT (`factory.constants`) so it
is trivially adjustable later. The unit tests mock httpx → format-independent.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx

from factory.constants import (
    MOBILEPROXY_AUTH_HEADER,
    MOBILEPROXY_AUTH_SCHEME,
    MOBILEPROXY_BASE_URL,
    MOBILEPROXY_ENDPOINT_BALANCE,
    MOBILEPROXY_ENDPOINT_BUY,
    MOBILEPROXY_ENDPOINT_REFUND,
    MOBILEPROXY_FIELD_BALANCE,
    MOBILEPROXY_FIELD_EXPIRES_AT,
    MOBILEPROXY_FIELD_HOST,
    MOBILEPROXY_FIELD_ID,
    MOBILEPROXY_FIELD_LOGIN,
    MOBILEPROXY_FIELD_PASSWORD,
    MOBILEPROXY_FIELD_PORT_SOCKS,
    MOBILEPROXY_HTTP_FORBIDDEN,
    MOBILEPROXY_HTTP_OK_CEIL,
    MOBILEPROXY_HTTP_OK_FLOOR,
    MOBILEPROXY_HTTP_TIMEOUT_SECONDS,
    MOBILEPROXY_HTTP_UNAUTHORIZED,
    MOBILEPROXY_PARAM_COUNTRY,
    MOBILEPROXY_PARAM_PROXY_ID,
    MOBILEPROXY_PROXY_SCHEME,
    MOBILEPROXY_STATUS_FIELD,
    MOBILEPROXY_STATUS_NO_STOCK,
)
from factory.errors import (
    ProxyProviderAuthError,
    ProxyProviderError,
    ProxyProviderResponseError,
    ProxyUnavailableError,
)
from factory.proxy.base import ProxyLease

logger = logging.getLogger(__name__)


def _coerce_scalar(value: object) -> str | None:
    """Normalise a JSON scalar (`str` or `int`) to `str`; everything else → `None`.

    The id/host/login/password may arrive as a string or (for the port) a JSON
    integer — both are valid → coerce. `bool` is an `int` subclass and is NOT a valid
    field, so it is excluded.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


class MobileProxyProvider:
    """Production Mobileproxy.space client (structurally satisfies `ProxyProvider`)."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = MOBILEPROXY_BASE_URL,
    ) -> None:
        # The api_key is held only to put in the Bearer header; NEVER logged.
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def allocate(self, country: str | None) -> ProxyLease:
        params: dict[str, str] = {}
        if country is not None:
            params[MOBILEPROXY_PARAM_COUNTRY] = country
        body = await self._call(MOBILEPROXY_ENDPOINT_BUY, params=params)
        return self._build_lease(body, country=country)

    async def release(self, lease_id: str) -> None:
        # BEST-EFFORT release: refunding a dead/expired port must NEVER raise — a raise
        # here would mask the surrounding registration outcome. Log a warning (no secret).
        try:
            await self._call(
                MOBILEPROXY_ENDPOINT_REFUND,
                params={MOBILEPROXY_PARAM_PROXY_ID: lease_id},
            )
        except ProxyProviderError:
            logger.warning(
                "mobileproxy release best-effort failed (endpoint=%s)",
                MOBILEPROXY_ENDPOINT_REFUND,
            )

    async def balance(self) -> Decimal:
        body = await self._call(MOBILEPROXY_ENDPOINT_BALANCE, params={})
        raw = body.get(MOBILEPROXY_FIELD_BALANCE)
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise ProxyProviderResponseError(
                f"mobileproxy unexpected balance shape (endpoint={MOBILEPROXY_ENDPOINT_BALANCE})"
            )
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            raise ProxyProviderResponseError(
                f"mobileproxy unparseable balance (endpoint={MOBILEPROXY_ENDPOINT_BALANCE})"
            ) from None

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        await self._client.aclose()

    # --- internals -------------------------------------------------------------

    def _build_lease(self, body: dict[str, object], *, country: str | None) -> ProxyLease:
        """Build a `ProxyLease` from a buyProxy body — never leak a secret on failure."""
        # Out-of-stock: a 200 body that reports no port is available is a TRANSIENT signal
        # (caller backs off / falls back to the static pool, no failed row) → typed
        # ProxyUnavailableError, mirroring SMSPVA's get_number response=2. The exact wire
        # value is confirmed on the free 2h trial at the final gate (like every field below).
        if body.get(MOBILEPROXY_STATUS_FIELD) == MOBILEPROXY_STATUS_NO_STOCK:
            raise ProxyUnavailableError(
                f"mobileproxy no proxy available (endpoint={MOBILEPROXY_ENDPOINT_BUY})"
            )
        lease_id = _coerce_scalar(body.get(MOBILEPROXY_FIELD_ID))
        host = _coerce_scalar(body.get(MOBILEPROXY_FIELD_HOST))
        port = _coerce_scalar(body.get(MOBILEPROXY_FIELD_PORT_SOCKS))
        login = _coerce_scalar(body.get(MOBILEPROXY_FIELD_LOGIN))
        password = _coerce_scalar(body.get(MOBILEPROXY_FIELD_PASSWORD))
        if lease_id is None or host is None or port is None or login is None or password is None:
            # Incomplete body — NEVER include the partial values (could carry creds).
            raise ProxyProviderResponseError(
                f"mobileproxy incomplete buyProxy body (endpoint={MOBILEPROXY_ENDPOINT_BUY})"
            )
        uri = f"{MOBILEPROXY_PROXY_SCHEME}://{login}:{password}@{host}:{port}"
        return ProxyLease(
            lease_id=lease_id,
            uri=uri,
            country=country,
            expires_at=self._parse_expires(body.get(MOBILEPROXY_FIELD_EXPIRES_AT)),
        )

    @staticmethod
    def _parse_expires(value: object) -> datetime | None:
        """Parse an ISO-8601 `expires_at` if present/valid; otherwise `None` (sticky)."""
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    async def _call(self, endpoint: str, *, params: dict[str, str]) -> dict[str, object]:
        """Issue one Bearer-authed GET and return the parsed JSON object."""
        headers = {MOBILEPROXY_AUTH_HEADER: f"{MOBILEPROXY_AUTH_SCHEME} {self._api_key}"}
        url = f"{self._base_url}{endpoint}"
        try:
            response = await self._client.get(url, params=params, headers=headers)
        except httpx.HTTPError:
            # Suppress the cause: the httpx exception repr contains the full request URL
            # and could surface request context — chaining it risks leaking via __cause__.
            raise ProxyProviderResponseError(
                f"mobileproxy transport error (endpoint={endpoint})"
            ) from None
        return self._json_body(response, endpoint=endpoint)

    @staticmethod
    def _json_body(response: httpx.Response, *, endpoint: str) -> dict[str, object]:
        """Parse a 2xx JSON object; auth/non-2xx/malformed/non-object → typed error."""
        status = response.status_code
        if status in (MOBILEPROXY_HTTP_UNAUTHORIZED, MOBILEPROXY_HTTP_FORBIDDEN):
            # Bad/expired Bearer token — NEVER include the token or the body.
            raise ProxyProviderAuthError(f"mobileproxy auth rejected (endpoint={endpoint})")
        if not (MOBILEPROXY_HTTP_OK_FLOOR <= status < MOBILEPROXY_HTTP_OK_CEIL):
            # Never include the body — status only.
            raise ProxyProviderResponseError(f"mobileproxy http {status} (endpoint={endpoint})")
        try:
            body = response.json()
        except ValueError:
            raise ProxyProviderResponseError(
                f"mobileproxy malformed JSON (endpoint={endpoint})"
            ) from None
        if not isinstance(body, dict):
            raise ProxyProviderResponseError(
                f"mobileproxy unexpected JSON shape (endpoint={endpoint})"
            )
        return body


def build_mobileproxy_provider(
    *,
    api_key: str,
    base_url: str = MOBILEPROXY_BASE_URL,
    timeout_seconds: float = MOBILEPROXY_HTTP_TIMEOUT_SECONDS,
) -> MobileProxyProvider:
    """Build a production `MobileProxyProvider` (httpx). Lazy — no network at import."""
    client = httpx.AsyncClient(timeout=timeout_seconds)
    return MobileProxyProvider(api_key=api_key, client=client, base_url=base_url)
