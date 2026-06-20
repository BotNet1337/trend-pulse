"""SMSPVA RENTAL provider over httpx (TASK-143) — long-lived REAL-SIM numbers.

The Activation path (`smspva.py`, `get_number`, service `opt1`) was live-proven to yield
numbers Telegram rejects (`PhoneNumberInvalid`) or never delivers the SMS to. The RENTAL
API (`/api/rent.php`, GET, service `opt29`) leases real-SIM numbers that Telegram accepts.

This provider structurally satisfies the SAME `SmsProvider` Protocol as `SmsPvaProvider`,
so `factory_tick` is UNCHANGED — only the impl + env-select differ. It MIRRORS
`smspva.py`'s structure and secret-redaction exactly: the `apikey` is a query param (a
SECRET); error messages name the method/status only and NEVER echo the body, params, or
the key. httpx exception chaining is suppressed (`from None`) so the request URL — which
carries `apikey=…` — cannot leak via `__cause__`.

Rent flow mapped onto `SmsProvider`:
  * `buy_number` → create (rental service opt29) → activate → poll `orders` until
    `state==1` (bounded) → `PurchasedNumber(id, ccode+pnumber)`.
  * `poll_code`  → poll `sms`; take the max-`date` SmsList entry; regex the code.
  * `finish`     → NO-OP: a rented number is KEPT alive for re-login during probation.
  * `cancel`     → `delete` (best-effort release on a failed registration; never raises).
  * `balance`    → rent.php has no balance method → the activation `priemnik.php` endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from decimal import Decimal, InvalidOperation

import httpx

from factory.constants import (
    RENT_ACTIVATION_POLL_INTERVAL_SECONDS,
    RENT_ACTIVATION_WAIT_TIMEOUT_SECONDS,
    RENT_BASE_PATH,
    RENT_CODE_REGEX,
    RENT_DCOUNT_DEFAULT,
    RENT_DTYPE_DEFAULT,
    RENT_FIELD_CCODE,
    RENT_FIELD_DATA,
    RENT_FIELD_DATE,
    RENT_FIELD_ID,
    RENT_FIELD_MSG,
    RENT_FIELD_PNUMBER,
    RENT_FIELD_SMSLIST,
    RENT_FIELD_STATE,
    RENT_FIELD_STATUS,
    RENT_FIELD_TEXT,
    RENT_HTTP_TIMEOUT_SECONDS,
    RENT_METOD_ACTIVATE,
    RENT_METOD_CREATE,
    RENT_METOD_DELETE,
    RENT_METOD_ORDERS,
    RENT_METOD_SMS,
    RENT_MSG_BAD_ID_FRAGMENTS,
    RENT_MSG_INSUFFICIENT_BALANCE,
    RENT_MSG_NO_STOCK_FRAGMENTS,
    RENT_PARAM_APIKEY,
    RENT_PARAM_COUNTRY,
    RENT_PARAM_DCOUNT,
    RENT_PARAM_DTYPE,
    RENT_PARAM_ID,
    RENT_PARAM_METHOD,
    RENT_PARAM_SERVICE,
    RENT_SMS_POLL_INTERVAL_SECONDS,
    RENT_STATE_ACTIVE,
    RENT_STATUS_OK,
    RENT_SVC_TELEGRAM,
    SMSPVA_BASE_URL,
    SMSPVA_ENDPOINT_PATH,
    SMSPVA_FIELD_BALANCE,
    SMSPVA_HTTP_OK_CEIL,
    SMSPVA_HTTP_OK_FLOOR,
    SMSPVA_METOD_BALANCE,
    SMSPVA_PARAM_APIKEY,
    SMSPVA_PARAM_METOD,
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

# Auth-failure `msg` fragments (lower-cased match) → SmsProviderAuthError. A bad/expired
# key is reported in free text by rent.php; documented fragments are matched here.
_AUTH_MSG_FRAGMENTS = ("invalid apikey", "api key", "unauthorized", "invalid key")

_CODE_RE = re.compile(RENT_CODE_REGEX)


def _coerce_id(value: object) -> str | None:
    """Normalise a rental `id` (JSON int or str) to `str`; everything else → `None`.

    `bool` is a subclass of `int` and is NOT a valid id, so it is excluded.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


class SmsPvaRentProvider:
    """Production SMSPVA RENTAL client over httpx (structurally satisfies `SmsProvider`)."""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        base_url: str = SMSPVA_BASE_URL,
        service: str = RENT_SVC_TELEGRAM,
        dtype: str = RENT_DTYPE_DEFAULT,
        dcount: int = RENT_DCOUNT_DEFAULT,
    ) -> None:
        # The api_key is held only to put in the `apikey` query param; never logged.
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")
        # The rental service slug used for `create` (opt29 = Telegram). The SmsProvider
        # `service` arg (the activation slug opt1) does NOT apply to rentals.
        self._service = service
        self._dtype = dtype
        self._dcount = dcount

    async def balance(self) -> Decimal:
        # rent.php has NO balance method → the account-wide balance lives on the
        # activation endpoint (priemnik.php). Reuses the SMSPVA_* balance constants.
        body = await self._call_activation_balance()
        raw = body.get(SMSPVA_FIELD_BALANCE)
        if not isinstance(raw, str):
            raise SmsProviderResponseError(
                f"smspva-rent unexpected balance shape (metod={SMSPVA_METOD_BALANCE})"
            )
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise SmsProviderResponseError(
                f"smspva-rent unparseable balance (metod={SMSPVA_METOD_BALANCE})"
            ) from exc

    async def buy_number(self, *, country: str, service: str) -> PurchasedNumber:
        # NOTE: `service` (the activation slug, e.g. opt1) is intentionally IGNORED for
        # rentals — `create` always uses the configured rental service (opt29). The arg
        # is kept only to satisfy the SmsProvider Protocol shape.
        del service
        created = await self._create(country=country)
        rent_id = _coerce_id(created.get(RENT_FIELD_ID))
        ccode = created.get(RENT_FIELD_CCODE)
        pnumber = _coerce_id(created.get(RENT_FIELD_PNUMBER))
        if rent_id is None or not isinstance(ccode, str) or pnumber is None:
            raise SmsProviderResponseError(
                f"smspva-rent unexpected create shape (method={RENT_METOD_CREATE})"
            )
        await self._activate(rent_id)
        await self._wait_until_active(rent_id)
        return PurchasedNumber(order_id=rent_id, phone=f"{ccode}{pnumber}")

    async def poll_code(self, order_id: str, *, timeout_seconds: int) -> str:
        deadline = time.monotonic() + timeout_seconds
        while True:
            body = await self._call(RENT_METOD_SMS, id=order_id)
            self._require_ok(body, method=RENT_METOD_SMS)
            code = self._extract_code(body)
            if code is not None:
                return code
            if time.monotonic() + RENT_SMS_POLL_INTERVAL_SECONDS > deadline:
                raise SmsCodeTimeoutError(
                    f"smspva-rent code not received within budget (method={RENT_METOD_SMS})"
                )
            await asyncio.sleep(RENT_SMS_POLL_INTERVAL_SECONDS)

    async def finish(self, order_id: str) -> None:
        # NO-OP (best-effort): a rented number is KEPT ALIVE so the account can re-login
        # during probation. We do NOT delete it on a successful registration — deleting
        # would release the real SIM and break re-auth. (Contrast `cancel`, which DOES
        # delete a rental whose registration failed.)
        del order_id
        return None

    async def cancel(self, order_id: str) -> None:
        # BEST-EFFORT release of a rental whose registration failed — must NEVER raise
        # (the rental may already be deleted/expired). Mirrors smspva.py's cancel.
        try:
            await self._call(RENT_METOD_DELETE, id=order_id)
        except SmsProviderError:
            logger.warning("smspva-rent cancel best-effort failed (method=%s)", RENT_METOD_DELETE)

    async def aclose(self) -> None:
        """Release transport resources (best-effort)."""
        await self._client.aclose()

    # --- rent.php operations ---------------------------------------------------

    async def _create(self, *, country: str) -> dict[str, object]:
        """`create` a rental → return the first `data[]` entry (id/pnumber/ccode/until)."""
        body = await self._call(
            RENT_METOD_CREATE,
            country=country,
            service=self._service,
            dtype=self._dtype,
            dcount=str(self._dcount),
        )
        self._require_ok(body, method=RENT_METOD_CREATE)
        data = body.get(RENT_FIELD_DATA)
        if not isinstance(data, list) or not data:
            raise SmsProviderResponseError(
                f"smspva-rent empty create data (method={RENT_METOD_CREATE})"
            )
        first = data[0]
        if not isinstance(first, dict):
            raise SmsProviderResponseError(
                f"smspva-rent unexpected create entry (method={RENT_METOD_CREATE})"
            )
        return first

    async def _activate(self, rent_id: str) -> None:
        """`activate` a created rental (required before it transitions to active)."""
        body = await self._call(RENT_METOD_ACTIVATE, id=rent_id)
        self._require_ok(body, method=RENT_METOD_ACTIVATE)

    async def _wait_until_active(self, rent_id: str) -> None:
        """Poll `orders` until this rental's `state == active`, bounded by the timeout."""
        deadline = time.monotonic() + RENT_ACTIVATION_WAIT_TIMEOUT_SECONDS
        while True:
            body = await self._call(RENT_METOD_ORDERS)
            self._require_ok(body, method=RENT_METOD_ORDERS)
            if self._order_state(body, rent_id) == RENT_STATE_ACTIVE:
                return
            if time.monotonic() + RENT_ACTIVATION_POLL_INTERVAL_SECONDS > deadline:
                # Never went active within the budget — treat like a code timeout so the
                # factory off-ramps this number (and releases via cancel) rather than hang.
                raise SmsCodeTimeoutError(
                    f"smspva-rent rental not active within budget (method={RENT_METOD_ORDERS})"
                )
            await asyncio.sleep(RENT_ACTIVATION_POLL_INTERVAL_SECONDS)

    @staticmethod
    def _order_state(body: dict[str, object], rent_id: str) -> int | None:
        """Return the integer `state` of `rent_id` in the `orders` data list, or None."""
        data = body.get(RENT_FIELD_DATA)
        if not isinstance(data, list):
            return None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if _coerce_id(entry.get(RENT_FIELD_ID)) != rent_id:
                continue
            state = entry.get(RENT_FIELD_STATE)
            if isinstance(state, int) and not isinstance(state, bool):
                return state
            return None
        return None

    @staticmethod
    def _extract_code(body: dict[str, object]) -> str | None:
        """Extract the Telegram code from the max-`date` SmsList entry, or None if none yet.

        Tolerates `data` missing/empty/non-object and an absent/empty `SmsList` as "not
        yet". Picks the newest message (max `date`) and regexes a 5-6 digit login code
        (not embedded in a longer digit run, so a phone number cannot be partially matched)
        from its `text`.
        """
        data = body.get(RENT_FIELD_DATA)
        if not isinstance(data, dict):
            return None
        sms_list = data.get(RENT_FIELD_SMSLIST)
        if not isinstance(sms_list, list) or not sms_list:
            return None
        entries = [e for e in sms_list if isinstance(e, dict)]
        if not entries:
            return None

        def _date(entry: dict[str, object]) -> int:
            raw = entry.get(RENT_FIELD_DATE)
            return raw if isinstance(raw, int) and not isinstance(raw, bool) else 0

        newest = max(entries, key=_date)
        text = newest.get(RENT_FIELD_TEXT)
        if not isinstance(text, str):
            return None
        match = _CODE_RE.search(text)
        return match.group(0) if match else None

    # --- transport + envelope --------------------------------------------------

    async def _call(
        self,
        method: str,
        *,
        country: str | None = None,
        service: str | None = None,
        dtype: str | None = None,
        dcount: str | None = None,
        id: str | None = None,
    ) -> dict[str, object]:
        """Issue one GET to rent.php and return the parsed JSON object (maps faults)."""
        params: dict[str, str] = {
            RENT_PARAM_METHOD: method,
            RENT_PARAM_APIKEY: self._api_key,
        }
        if country is not None:
            params[RENT_PARAM_COUNTRY] = country
        if service is not None:
            params[RENT_PARAM_SERVICE] = service
        if dtype is not None:
            params[RENT_PARAM_DTYPE] = dtype
        if dcount is not None:
            params[RENT_PARAM_DCOUNT] = dcount
        if id is not None:
            params[RENT_PARAM_ID] = id
        url = f"{self._base_url}{RENT_BASE_PATH}"
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError:
            # Suppress the cause: the httpx exception repr contains the full request URL
            # (including apikey=…) — chaining it would leak the secret via __cause__.
            raise SmsProviderResponseError(
                f"smspva-rent transport error (method={method})"
            ) from None
        return self._json_body(response, method=method)

    async def _call_activation_balance(self) -> dict[str, object]:
        """Issue the activation-endpoint balance GET (priemnik.php) — no rent.php method."""
        params = {
            SMSPVA_PARAM_METOD: SMSPVA_METOD_BALANCE,
            SMSPVA_PARAM_APIKEY: self._api_key,
        }
        url = f"{self._base_url}{SMSPVA_ENDPOINT_PATH}"
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError:
            raise SmsProviderResponseError(
                f"smspva-rent transport error (metod={SMSPVA_METOD_BALANCE})"
            ) from None
        return self._json_body(response, method=SMSPVA_METOD_BALANCE)

    @staticmethod
    def _json_body(response: httpx.Response, *, method: str) -> dict[str, object]:
        """Parse a 2xx JSON object; non-2xx/malformed/non-object → response error."""
        if not (SMSPVA_HTTP_OK_FLOOR <= response.status_code < SMSPVA_HTTP_OK_CEIL):
            # Never include the body — it could echo request params; status only.
            raise SmsProviderResponseError(
                f"smspva-rent http {response.status_code} (method={method})"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise SmsProviderResponseError(f"smspva-rent malformed JSON (method={method})") from exc
        if not isinstance(body, dict):
            raise SmsProviderResponseError(f"smspva-rent unexpected JSON shape (method={method})")
        return body

    def _require_ok(self, body: dict[str, object], *, method: str) -> None:
        """Raise the right typed error unless the envelope `status` is the success int.

        On a `status:0` failure, the free-text `msg` is matched against documented
        fragments to pick the typed error (no stock → unavailable, auth → auth error,
        else response error). The `msg` itself is NEVER echoed (it cannot contain the
        apikey, but we keep the redaction discipline uniform).
        """
        status = body.get(RENT_FIELD_STATUS)
        if status == RENT_STATUS_OK:
            return
        msg = body.get(RENT_FIELD_MSG)
        msg_lc = msg.lower() if isinstance(msg, str) else ""
        if any(frag in msg_lc for frag in RENT_MSG_NO_STOCK_FRAGMENTS):
            raise SmsNumberUnavailableError(f"smspva-rent no number available (method={method})")
        if any(frag in msg_lc for frag in _AUTH_MSG_FRAGMENTS):
            raise SmsProviderAuthError(f"smspva-rent auth rejected (method={method})")
        if RENT_MSG_INSUFFICIENT_BALANCE in msg_lc:
            raise SmsProviderResponseError(f"smspva-rent insufficient balance (method={method})")
        if any(frag in msg_lc for frag in RENT_MSG_BAD_ID_FRAGMENTS):
            raise SmsProviderResponseError(f"smspva-rent bad order id (method={method})")
        raise SmsProviderResponseError(f"smspva-rent response status={status} (method={method})")


def build_smspva_rent_provider(
    *,
    api_key: str,
    base_url: str = SMSPVA_BASE_URL,
    service: str = RENT_SVC_TELEGRAM,
    dtype: str = RENT_DTYPE_DEFAULT,
    dcount: int = RENT_DCOUNT_DEFAULT,
    timeout_seconds: float = RENT_HTTP_TIMEOUT_SECONDS,
) -> SmsPvaRentProvider:
    """Build a production `SmsPvaRentProvider` (httpx). Lazy — no network at import."""
    client = httpx.AsyncClient(timeout=timeout_seconds)
    return SmsPvaRentProvider(
        api_key=api_key,
        client=client,
        base_url=base_url,
        service=service,
        dtype=dtype,
        dcount=dcount,
    )
