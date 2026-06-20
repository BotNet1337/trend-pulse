"""Domain errors for the account factory (CONVENTIONS: explicit errors, no bare except)."""


class FactoryError(Exception):
    """Base class for all account-factory domain errors (TASK-132)."""


class FactoryAccountStoreError(FactoryError):
    """Base for the `factory_accounts` store errors (TASK-132)."""


class FactoryAccountValidationError(FactoryAccountStoreError):
    """A value handed to the store violated a domain invariant before persistence.

    Raised by `create_purchased` when `phone_masked` is not actually masked (does not
    contain the mask char) — a guard against silently persisting a full, unmasked phone
    (PII). The offending value is NEVER included in the message."""


class FactoryAccountNotFoundError(FactoryAccountStoreError):
    """A `transition` (or lookup) referenced a `factory_accounts` row that does not exist.

    Raised by `transition` when no row matches the given account id. The factory loop
    treats this as a programmer/data error (the row should exist for the lifecycle it
    is driving) rather than a recoverable state."""


class IllegalFactoryTransitionError(FactoryAccountStoreError):
    """A requested state transition is not in `ALLOWED_TRANSITIONS[current_state]`.

    Raised by `transition` when the target state is illegal from the row's current
    state (e.g. `purchased → promoted`, skipping registration/probation). Guards the
    lifecycle invariant: an account can only be promoted into the pool after probation."""


# --- SMS provider errors (TASK-133). Mapped at the SMSPVA HTTP boundary; messages
# carry status/metod only — NEVER the response body, params, or the api_key. ---
class SmsProviderError(FactoryError):
    """Base for all SMS-provider (e.g. SMSPVA) domain errors."""


class SmsProviderAuthError(SmsProviderError):
    """The provider rejected the API key (response=`error`/auth failure).

    Raised when SMSPVA returns the `error` status (bad/expired key). The provider's
    `error_msg` and the api_key are NEVER included in the message."""


class SmsNumberUnavailableError(SmsProviderError):
    """No phone number is currently available to buy (get_number response=2).

    A transient condition — the caller (TASK-134) retries after a backoff. Also the
    scripted failure used by the fake's `banned` scenario."""


class SmsCodeTimeoutError(SmsProviderError):
    """The SMS verification code never arrived within the poll budget.

    Raised by `poll_code` when the timeout elapses with no code, or when the order id
    is reported invalid/expired (get_sms response=3)."""


class SmsProviderResponseError(SmsProviderError):
    """A non-OK or malformed provider response (TASK-133).

    Covers non-2xx HTTP, malformed/non-object JSON, unexpected response shapes, and
    the global error codes (5 rate-limit / 6 negative-karma ban / 7 concurrent-stream
    limit), plus finish/cancel failures. The message names the metod and status only —
    NEVER the response body or the api_key (which could leak the secret)."""


# --- Proxy provider errors (TASK-139). Mapped at the Mobileproxy.space HTTP boundary;
# messages carry the endpoint only — NEVER the response body, the proxy URI (carries
# user:pass creds), or the api token (Bearer secret). ---
class ProxyProviderError(FactoryError):
    """Base for all proxy-provider (e.g. Mobileproxy.space) domain errors.

    Mirrors `SmsProviderError`: the dynamic allocate/release/balance surface raises
    only typed subclasses — never sentinel values or the transport's exceptions. The
    proxy URI and the api token are NEVER included in the message."""


class ProxyProviderAuthError(ProxyProviderError):
    """The provider rejected the API token (HTTP 401/403 / auth failure).

    Raised when the upstream rejects the Bearer token. The token is NEVER included in
    the message (it would leak the secret)."""


class ProxyUnavailableError(ProxyProviderError):
    """No proxy port is currently available to allocate (provider out of stock).

    A transient condition — the caller retries after a backoff or falls back to the
    static pool. Mirrors `SmsNumberUnavailableError`."""


class ProxyProviderResponseError(ProxyProviderError):
    """A non-OK or malformed provider response (TASK-139).

    Covers non-2xx HTTP, malformed/non-object JSON, unexpected/incomplete buyProxy
    shapes (missing host/port/id), an unparseable balance, and transport faults. The
    message names the endpoint only — NEVER the response body, the proxy URI, or the
    api token (which could leak a secret)."""


# --- Telegram registrar errors (TASK-133). Raised by the real Telethon registrar. ---
class RegistrarError(FactoryError):
    """Base for all Telegram-registrar domain errors."""


class RegistrarBannedError(RegistrarError):
    """Telegram banned/blocked the phone number (PHONE_NUMBER_BANNED).

    Terminal for that number — the factory moves the account to `banned`. The phone
    number is a secret and is NEVER included in the message."""


class RegistrarPasswordNeededError(RegistrarError):
    """The account has 2FA enabled and a cloud password is required (SESSION_PASSWORD_NEEDED).

    The registrar cannot complete sign-in without the 2FA password; the caller treats
    this as a registration failure for that number."""
