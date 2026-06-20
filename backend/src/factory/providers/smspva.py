"""Real SMSPVA REST provider over httpx (TASK-133) — mirrors collector/twitter/client.

All calls are GET to `{base_url}{SMSPVA_ENDPOINT_PATH}` with the api-key as a query
param. Responses are JSON; the status field is read tolerating BOTH `response` and
the API's misspelled `responce` key. Non-OK HTTP, malformed JSON, and the global
error codes map to typed `SmsProviderError` subclasses — error messages name the
metod/status only and NEVER echo the body, params, or the api_key (secret).
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal, InvalidOperation

import httpx

from factory.constants import (
    SMS_CODE_POLL_INTERVAL_SECONDS,
    SMSPVA_BASE_URL,
    SMSPVA_ENDPOINT_PATH,
    SMSPVA_FIELD_BALANCE,
    SMSPVA_FIELD_ID,
    SMSPVA_FIELD_NUMBER,
    SMSPVA_FIELD_RESPONSE,
    SMSPVA_FIELD_RESPONSE_ALT,
    SMSPVA_FIELD_SMS,
    SMSPVA_HTTP_OK_CEIL,
    SMSPVA_HTTP_OK_FLOOR,
    SMSPVA_HTTP_TIMEOUT_SECONDS,
    SMSPVA_METOD_BALANCE,
    SMSPVA_METOD_BAN,
    SMSPVA_METOD_DENIAL,
    SMSPVA_METOD_NUMBER,
    SMSPVA_METOD_SMS,
    SMSPVA_PARAM_APIKEY,
    SMSPVA_PARAM_COUNTRY,
    SMSPVA_PARAM_ID,
    SMSPVA_PARAM_METOD,
    SMSPVA_PARAM_SERVICE,
    SMSPVA_RESPONSE_ERROR,
    SMSPVA_RESPONSE_INVALID_ID,
    SMSPVA_RESPONSE_OK,
    SMSPVA_RESPONSE_WAIT,
)
from factory.errors import (
    SmsCodeTimeoutError,
    SmsNumberUnavailableError,
    SmsProviderAuthError,
    SmsProviderError,
    SmsProviderResponseError,
)
from factory.providers.base import PurchasedNumber

logger = logging.getLogger(__name__)


def _coerce_scalar(value: object) -> str | None:
    """Normalise a JSON scalar (`str` or `int`) to `str`; everything else → `None`.

    SMSPVA returns `number`/`id` as a string for most countries but as a JSON integer
    for some — both are valid identifiers, so coerce instead of rejecting. `bool` is a
    subclass of `int` and is NOT a valid id, so it is excluded.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


class SmsPvaProvider:
    """Production SMSPVA client over httpx (structurally satisfies `SmsProvider`)."""

    def __init__(
        self, *, api_key: str, client: httpx.AsyncClient, base_url: str = SMSPVA_BASE_URL
    ) -> None:
        # The api_key is held only to put in the `apikey` query param; never logged.
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def balance(self) -> Decimal:
        body = await self._call(SMSPVA_METOD_BALANCE)
        self._require_ok(body, metod=SMSPVA_METOD_BALANCE)
        raw = body.get(SMSPVA_FIELD_BALANCE)
        if not isinstance(raw, str):
            raise SmsProviderResponseError(
                f"smspva unexpected balance shape (metod={SMSPVA_METOD_BALANCE})"
            )
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise SmsProviderResponseError(
                f"smspva unparseable balance (metod={SMSPVA_METOD_BALANCE})"
            ) from exc

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        body = await self._call(SMSPVA_METOD_NUMBER, country=country, service=service)
        status = self._status(body)
        if status == SMSPVA_RESPONSE_WAIT:
            # No number available right now — transient; caller retries after a backoff.
            raise SmsNumberUnavailableError(
                f"smspva no number available (metod={SMSPVA_METOD_NUMBER})"
            )
        self._require_ok(body, metod=SMSPVA_METOD_NUMBER)
        # SMSPVA returns `number`/`id` as a STRING for most countries but as a JSON
        # INTEGER for some (observed live: ID/PH) — coerce int|str → str so a real,
        # buyable number is NOT discarded as an "unexpected shape" (which would make the
        # factory skip a country that actually has stock). Reject only None/other types.
        number = _coerce_scalar(body.get(SMSPVA_FIELD_NUMBER))
        order_id = _coerce_scalar(body.get(SMSPVA_FIELD_ID))
        if number is None or order_id is None:
            raise SmsProviderResponseError(
                f"smspva unexpected number shape (metod={SMSPVA_METOD_NUMBER})"
            )
        return PurchasedNumber(order_id=order_id, phone=number)

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        deadline = time.monotonic() + timeout_seconds
        while True:
            body = await self._call(SMSPVA_METOD_SMS, id=order_id)
            status = self._status(body)
            if status == SMSPVA_RESPONSE_OK:
                sms = body.get(SMSPVA_FIELD_SMS)
                if not isinstance(sms, str) or not sms:
                    raise SmsProviderResponseError(
                        f"smspva code-ready but empty sms (metod={SMSPVA_METOD_SMS})"
                    )
                return sms
            if status == SMSPVA_RESPONSE_INVALID_ID:
                # Invalid/expired order id — the code will never arrive for this order.
                raise SmsCodeTimeoutError(
                    f"smspva order invalid/expired (metod={SMSPVA_METOD_SMS})"
                )
            if status != SMSPVA_RESPONSE_WAIT:
                # Any non-wait, non-ok status (rate-limit/karma/stream/error) is fatal.
                self._require_ok(body, metod=SMSPVA_METOD_SMS)
            if time.monotonic() + SMS_CODE_POLL_INTERVAL_SECONDS > deadline:
                raise SmsCodeTimeoutError(
                    f"smspva code not received within budget (metod={SMSPVA_METOD_SMS})"
                )
            await asyncio.sleep(SMS_CODE_POLL_INTERVAL_SECONDS)

    async def finish(self, order_id: str) -> None:
        # BEST-EFFORT cleanup: closing an order as used must never raise. Live evidence:
        # a consumed/expired order replies response=3 ("Invalid params"), which is fine
        # for cleanup — the order is already gone. Issuing the request is what releases it
        # server-side; the reply is only confirmation. A raise here would mask the real
        # outcome of the surrounding flow (e.g. a registration result).
        try:
            await self._call(SMSPVA_METOD_BAN, id=order_id)
        except SmsProviderError:
            logger.warning("smspva finish best-effort failed (metod=%s)", SMSPVA_METOD_BAN)

    async def cancel(self, order_id: str) -> None:
        # BEST-EFFORT release (same rationale as `finish`) — used to refund a number whose
        # registration failed; must NOT raise (the order may already be expired/invalid).
        try:
            await self._call(SMSPVA_METOD_DENIAL, id=order_id)
        except SmsProviderError:
            logger.warning("smspva cancel best-effort failed (metod=%s)", SMSPVA_METOD_DENIAL)

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        await self._client.aclose()

    # --- internals -------------------------------------------------------------

    async def _call(
        self,
        metod: str,
        *,
        country: str | None = None,
        service: str | None = None,
        id: str | None = None,
    ) -> dict[str, object]:
        """Issue one GET and return the parsed JSON object (maps transport faults)."""
        params: dict[str, str] = {
            SMSPVA_PARAM_METOD: metod,
            SMSPVA_PARAM_APIKEY: self._api_key,
        }
        if service is not None:
            params[SMSPVA_PARAM_SERVICE] = service
        if country is not None:
            params[SMSPVA_PARAM_COUNTRY] = country
        if id is not None:
            params[SMSPVA_PARAM_ID] = id
        url = f"{self._base_url}{SMSPVA_ENDPOINT_PATH}"
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError:
            # Suppress the cause: httpx exception repr contains the full request URL
            # (including apikey=…) — chaining it would leak the secret via __cause__.
            raise SmsProviderResponseError(f"smspva transport error (metod={metod})") from None
        return self._json_body(response, metod=metod)

    @staticmethod
    def _json_body(response: httpx.Response, *, metod: str) -> dict[str, object]:
        """Parse a 2xx JSON object; non-2xx/malformed/non-object → response error."""
        if not (SMSPVA_HTTP_OK_FLOOR <= response.status_code < SMSPVA_HTTP_OK_CEIL):
            # Never include the body — it could echo request params; status only.
            raise SmsProviderResponseError(f"smspva http {response.status_code} (metod={metod})")
        try:
            body = response.json()
        except ValueError as exc:
            raise SmsProviderResponseError(f"smspva malformed JSON (metod={metod})") from exc
        if not isinstance(body, dict):
            raise SmsProviderResponseError(f"smspva unexpected JSON shape (metod={metod})")
        return body

    @staticmethod
    def _status(body: dict[str, object]) -> str | None:
        """Read the status field tolerating the API's `response`/`responce` misspelling."""
        status = body.get(SMSPVA_FIELD_RESPONSE, body.get(SMSPVA_FIELD_RESPONSE_ALT))
        return status if isinstance(status, str) else None

    def _require_ok(self, body: dict[str, object], *, metod: str) -> None:
        """Raise the right typed error unless the status is the success code."""
        status = self._status(body)
        if status == SMSPVA_RESPONSE_OK:
            return
        if status == SMSPVA_RESPONSE_ERROR:
            # Auth/key invalid — do NOT include error_msg (could echo key context).
            raise SmsProviderAuthError(f"smspva auth rejected (metod={metod})")
        # Rate-limit (5) / karma ban (6) / stream limit (7) / unexpected → response error.
        raise SmsProviderResponseError(f"smspva response status={status} (metod={metod})")


def build_smspva_provider(
    *,
    api_key: str,
    base_url: str = SMSPVA_BASE_URL,
    timeout_seconds: float = SMSPVA_HTTP_TIMEOUT_SECONDS,
) -> SmsPvaProvider:
    """Build a production `SmsPvaProvider` (httpx). Lazy — no network at import."""
    client = httpx.AsyncClient(timeout=timeout_seconds)
    return SmsPvaProvider(api_key=api_key, client=client, base_url=base_url)
