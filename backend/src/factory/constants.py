"""Account-factory state machine + column-width constants (TASK-132, Layer B3).

The factory provisions technical Telegram accounts through a lifecycle BEFORE they
ever enter the live pool (`pool_sessions`). The state machine mirrors the
`collector/constants.py` style: each state is a plain `Final[str]` constant, with a
`frozenset` of all states and a transition map (state → legal next states).

States (`purchased → registered → probation → promoted`, with `failed`/`banned` as
the off-ramps):
  * `purchased`  — a number/slot was bought from a provider; nothing registered yet.
  * `registered` — a Telegram account was registered; `session_string` + `tg_user_id` set.
  * `probation`  — the account is being warmed/health-checked before promotion.
  * `promoted`   — TERMINAL success: the session was copied into `pool_sessions`.
  * `failed`     — TERMINAL: provisioning failed (e.g. SMS never arrived) at some stage.
  * `banned`     — TERMINAL: Telegram banned/flagged the account.

Column widths are named constants (CONVENTIONS: no magic literals).
"""

from typing import Final

# --- States (plain Final constants — mirror collector/constants.py POOL_SOURCE_*). ---
FACTORY_STATE_PURCHASED: Final = "purchased"
FACTORY_STATE_REGISTERED: Final = "registered"
FACTORY_STATE_PROBATION: Final = "probation"
FACTORY_STATE_PROMOTED: Final = "promoted"
FACTORY_STATE_FAILED: Final = "failed"
FACTORY_STATE_BANNED: Final = "banned"

# The complete, validated set of factory states (membership checks, test coverage).
FACTORY_STATES: Final[frozenset[str]] = frozenset(
    {
        FACTORY_STATE_PURCHASED,
        FACTORY_STATE_REGISTERED,
        FACTORY_STATE_PROBATION,
        FACTORY_STATE_PROMOTED,
        FACTORY_STATE_FAILED,
        FACTORY_STATE_BANNED,
    }
)

# Legal state transitions (state → set of legal next states). The happy path is
# purchased → registered → probation → promoted; failure/ban are reachable from any
# non-terminal state (a number can be lost, or banned/flagged by the SMS provider — e.g.
# recognized as VoIP — even before Telegram registration). Terminal states
# (promoted/failed/banned) have NO outgoing transitions. An attempt outside this map
# (e.g. purchased → promoted) raises `IllegalFactoryTransitionError`.
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    FACTORY_STATE_PURCHASED: frozenset(
        {FACTORY_STATE_REGISTERED, FACTORY_STATE_FAILED, FACTORY_STATE_BANNED}
    ),
    FACTORY_STATE_REGISTERED: frozenset(
        {FACTORY_STATE_PROBATION, FACTORY_STATE_FAILED, FACTORY_STATE_BANNED}
    ),
    FACTORY_STATE_PROBATION: frozenset(
        {FACTORY_STATE_PROMOTED, FACTORY_STATE_FAILED, FACTORY_STATE_BANNED}
    ),
    FACTORY_STATE_PROMOTED: frozenset(),
    FACTORY_STATE_FAILED: frozenset(),
    FACTORY_STATE_BANNED: frozenset(),
}

# --- Column widths for the `factory_accounts` table (named constants). ---
# The mask sentinel a `phone_masked` value MUST contain (e.g. `+79*****1234`) — the store
# guards against silently persisting a full, unmasked number (no `*`).
FACTORY_PHONE_MASK_CHAR: Final = "*"
# Masked phone only (e.g. `+79*****1234`) — the full number is NEVER persisted.
FACTORY_PHONE_MASKED_MAX: Final = 32
# Provider slug (e.g. `sms-activate`) — short enum-like value.
FACTORY_PROVIDER_MAX: Final = 32
# Provider's order/activation id — opaque token from the upstream SMS provider.
FACTORY_PROVIDER_ORDER_ID_MAX: Final = 128
# Encrypted SOCKS5 proxy URI (carries user:pass creds). Mirrors POOL_SESSION_PROXY_MAX:
# plaintext is short (~50 chars) but Fernet ciphertext + base64 expansion adds overhead.
FACTORY_PROXY_MAX: Final = 512
# Encrypted Telethon StringSession. Mirrors POOL_SESSION_STRING_MAX: a StringSession is
# ~350 chars; Fernet adds ~89 bytes overhead + base64 expansion → a generous cap.
FACTORY_SESSION_STRING_MAX: Final = 1024
# The `state` string — a short enum-like value from FACTORY_STATES.
FACTORY_STATE_MAX: Final = 16
# Dynamic-proxy lease id (the provider's opaque port id) — NON-secret, plain VARCHAR.
# Generous cap for an opaque token (mobileproxy port ids are short numeric strings).
FACTORY_PROXY_LEASE_ID_MAX: Final = 128
# Last-error diagnostic message (non-secret) recorded on a failed/banned transition.
FACTORY_LAST_ERROR_MAX: Final = 512

# --- Provider selection (TASK-133). Chooses the SmsProvider/TelegramRegistrar impl
# from env `ACCOUNT_FACTORY_PROVIDER`; default `fake` keeps CI/this env network-free. ---
ACCOUNT_FACTORY_PROVIDER_FAKE: Final = "fake"
ACCOUNT_FACTORY_PROVIDER_SMSPVA: Final = "smspva"
# SMSPVA Rental path (TASK-143) — long-lived REAL-SIM numbers (Telegram service opt29)
# that Telegram accepts; the Activation path (`smspva`, opt1) was live-proven to yield
# PhoneNumberInvalid numbers. Selected like `smspva` but builds `SmsPvaRentProvider`.
ACCOUNT_FACTORY_PROVIDER_SMSPVA_RENT: Final = "smspva_rent"

# --- SMSPVA REST API (TASK-133). All calls are GET to {base}{path} with JSON bodies;
# the API-key is a query param (`apikey`) — a SECRET, never logged. ---
SMSPVA_BASE_URL: Final = "https://smspva.com"
SMSPVA_ENDPOINT_PATH: Final = "/priemnik.php"

# `metod` query values — one per operation in the buy → poll → finish/cancel flow.
SMSPVA_METOD_BALANCE: Final = "get_balance"
SMSPVA_METOD_NUMBER: Final = "get_number"
SMSPVA_METOD_SMS: Final = "get_sms"
SMSPVA_METOD_BAN: Final = "ban"
SMSPVA_METOD_DENIAL: Final = "denial"

# Query param names (no magic literals in smspva.py).
SMSPVA_PARAM_METOD: Final = "metod"
SMSPVA_PARAM_SERVICE: Final = "service"
SMSPVA_PARAM_APIKEY: Final = "apikey"
SMSPVA_PARAM_COUNTRY: Final = "country"
SMSPVA_PARAM_ID: Final = "id"

# Status field — the API misspells `response` as `responce` in some replies, so the
# provider reads BOTH keys. Response-code constants (the `response`/`responce` value):
SMSPVA_RESPONSE_OK: Final = "1"  # success
SMSPVA_RESPONSE_WAIT: Final = "2"  # get_number: unavailable / get_sms: code not yet
SMSPVA_RESPONSE_INVALID_ID: Final = "3"  # get_sms: invalid id / timeout expired
SMSPVA_RESPONSE_MISSED: Final = "4"  # get_sms: missed
SMSPVA_RESPONSE_RATE_LIMIT: Final = "5"  # per-minute request limit exceeded
SMSPVA_RESPONSE_KARMA_BAN: Final = "6"  # negative-karma ban (10 min)
SMSPVA_RESPONSE_STREAM_LIMIT: Final = "7"  # concurrent-stream limit
SMSPVA_RESPONSE_ERROR: Final = "error"  # auth/key invalid (carries error_msg)

# Response JSON field names read by the provider.
SMSPVA_FIELD_RESPONSE: Final = "response"
SMSPVA_FIELD_RESPONSE_ALT: Final = "responce"  # API misspelling — handled too
SMSPVA_FIELD_BALANCE: Final = "balance"
SMSPVA_FIELD_NUMBER: Final = "number"
SMSPVA_FIELD_ID: Final = "id"
SMSPVA_FIELD_SMS: Final = "sms"

# Default order target — overridable per buy_number call.
SMSPVA_DEFAULT_COUNTRY: Final = "RU"
SMSPVA_DEFAULT_SERVICE: Final = "opt1"  # Telegram service slug on SMSPVA.

# httpx client timeout for SMSPVA calls (seconds).
SMSPVA_HTTP_TIMEOUT_SECONDS: Final = 15.0

# SMS-code polling budget + per-attempt sleep (SECONDS, named — no magic literals).
# The interval matches the API's ~20s retry hint; the timeout bounds the whole loop.
SMS_CODE_POLL_TIMEOUT_SECONDS: Final = 300
SMS_CODE_POLL_INTERVAL_SECONDS: Final = 20

# httpx 2xx success band (mirrors collector/twitter/client._HTTP_OK_*).
SMSPVA_HTTP_OK_FLOOR: Final = 200
SMSPVA_HTTP_OK_CEIL: Final = 300

# --- SMSPVA RENTAL REST API (TASK-143). A SEPARATE endpoint (`/api/rent.php`, GET) that
# leases long-lived REAL-SIM numbers (Telegram service `opt29`) which Telegram accepts —
# unlike the Activation numbers (opt1, get_number) that were live-proven to be rejected
# (PhoneNumberInvalid). Implemented EXACTLY against the official rent.php OpenAPI schema.
# The api_key is a QUERY param (`apikey`) — a SECRET, never logged. ---
RENT_BASE_PATH: Final = "/api/rent.php"

# `method` query values — one per operation in the create→activate→poll→delete flow.
RENT_METOD_CREATE: Final = "create"
RENT_METOD_ACTIVATE: Final = "activate"
RENT_METOD_ORDERS: Final = "orders"
RENT_METOD_SMS: Final = "sms"
RENT_METOD_DELETE: Final = "delete"
RENT_METOD_GETDATA: Final = "getdataWithProviders"

# Query param names (no magic literals in smspva_rent.py).
RENT_PARAM_METHOD: Final = "method"
RENT_PARAM_APIKEY: Final = "apikey"
RENT_PARAM_DTYPE: Final = "dtype"
RENT_PARAM_DCOUNT: Final = "dcount"
RENT_PARAM_COUNTRY: Final = "country"
RENT_PARAM_SERVICE: Final = "service"
RENT_PARAM_ID: Final = "id"
RENT_PARAM_PROVIDER: Final = "provider"

# Telegram rental service slug. Rentals use THIS service for `create` — the SmsProvider
# `service` arg (the activation slug `opt1`) does NOT apply to rentals (documented in code).
RENT_SVC_TELEGRAM: Final = "opt29"

# Rent duration types. Min 7 / max 90 days → `dtype=week, dcount=1` (=7 days) is the
# smallest legal lease.
RENT_DTYPE_DAY: Final = "day"
RENT_DTYPE_WEEK: Final = "week"
RENT_DTYPE_MONTH: Final = "month"

# Envelope status — an INTEGER 1 (success) / 0 (failure, with a `msg` reason).
RENT_STATUS_OK: Final = 1
RENT_STATUS_FAIL: Final = 0

# Order `state` values (from the `orders` listing): poll until ACTIVE before SMS.
RENT_STATE_NOT_ACTIVE: Final = 0
RENT_STATE_ACTIVE: Final = 1
RENT_STATE_ACTIVATING: Final = 2
RENT_STATE_NOT_IN_SYSTEM: Final = -1

# Response JSON field names read by the provider.
RENT_FIELD_STATUS: Final = "status"
RENT_FIELD_MSG: Final = "msg"
RENT_FIELD_DATA: Final = "data"
RENT_FIELD_ID: Final = "id"
RENT_FIELD_PNUMBER: Final = "pnumber"
RENT_FIELD_CCODE: Final = "ccode"
RENT_FIELD_UNTIL: Final = "until"
RENT_FIELD_STATE: Final = "state"
RENT_FIELD_HASNEWSMS: Final = "hasnewsms"
RENT_FIELD_SMSLIST: Final = "SmsList"
RENT_FIELD_OTHERSMS: Final = "OtherSms"
RENT_FIELD_TEXT: Final = "text"
RENT_FIELD_DATE: Final = "date"
RENT_FIELD_SENDER: Final = "sender"
RENT_FIELD_SERVICES: Final = "services"
RENT_FIELD_PRICE_DAY: Final = "price_day"

# Failure-`msg` substrings (lower-cased match) → typed error mapping. The upstream `msg`
# is free text; we match documented fragments and fall back to a response error.
RENT_MSG_INSUFFICIENT_BALANCE: Final = "insufficient balance"
RENT_MSG_NO_STOCK_FRAGMENTS: Final = ("no number", "not available", "out of stock", "no stock")
RENT_MSG_BAD_ID_FRAGMENTS: Final = ("incorrect order id", "order not found", "incorrect order")

# Telegram code extractor — the SMS `text` is free text (e.g. "Telegram code: 12345");
# the login code is 5-6 digits. The lookarounds require the run to NOT be embedded in a
# longer digit sequence (so a phone number in the body cannot be partially matched).
# Bounded (5-6) → ReDoS-safe. Named so it is not a magic literal.
RENT_CODE_REGEX: Final = r"(?<!\d)\d{5,6}(?!\d)"

# Bound for waiting on a created rental to reach state==1 (active) after `activate`
# (SECONDS, named — no magic literals): the whole wait + per-poll sleep interval.
RENT_ACTIVATION_WAIT_TIMEOUT_SECONDS: Final = 120
RENT_ACTIVATION_POLL_INTERVAL_SECONDS: Final = 5

# SMS-code polling per-attempt sleep (SECONDS). The overall budget is passed by the
# caller (`poll_code(timeout_seconds=...)`); this is the gap between `sms` polls.
RENT_SMS_POLL_INTERVAL_SECONDS: Final = 10

# Default lease shape for a factory rental (env-overridable via config). week x1 = 7 days
# — the cheapest legal lease, enough to register + probation re-login.
RENT_DTYPE_DEFAULT: Final = RENT_DTYPE_WEEK
RENT_DCOUNT_DEFAULT: Final = 1

# httpx client timeout for SMSPVA rent calls (seconds) — mirrors SMSPVA.
RENT_HTTP_TIMEOUT_SECONDS: Final = 15.0

# --- Proxy provider selection (TASK-139, Layer B-proxy). Chooses the ProxyProvider impl
# from env `ACCOUNT_FACTORY_PROXY_PROVIDER`; unset/empty/unknown → None (static-pool
# fallback). `fake` keeps CI/this env network-free; `mobileproxy` is the live path. ---
ACCOUNT_FACTORY_PROXY_PROVIDER_FAKE: Final = "fake"
ACCOUNT_FACTORY_PROXY_PROVIDER_MOBILEPROXY: Final = "mobileproxy"

# --- Mobileproxy.space REST API (TASK-139). Bearer-authed JSON over httpx. The exact
# wire format is partly unverified publicly (confirmed on the free 2h trial at the
# final gate); base URL + endpoint paths + JSON field names are NAMED CONSTANTS so the
# format is trivially adjustable later. The unit tests mock httpx → format-independent.
# The api token (Bearer) and the built proxy URI (user:pass creds) are SECRETS, never
# logged. See docs/research/proxy-provider-comparison.md. ---
MOBILEPROXY_BASE_URL: Final = "https://mobileproxy.space"

# Endpoint paths (REST under the base). Named so the exact route is adjustable later.
MOBILEPROXY_ENDPOINT_BUY: Final = "/api/buyProxy"
MOBILEPROXY_ENDPOINT_REFUND: Final = "/api/refundProxy"
MOBILEPROXY_ENDPOINT_BALANCE: Final = "/api/getBalance"

# HTTP request header for the Bearer token (RFC 6750). The token is the secret.
MOBILEPROXY_AUTH_HEADER: Final = "Authorization"
MOBILEPROXY_AUTH_SCHEME: Final = "Bearer"

# Query param names sent to buyProxy/refundProxy.
MOBILEPROXY_PARAM_COUNTRY: Final = "country"
MOBILEPROXY_PARAM_PROXY_ID: Final = "proxy_id"

# Response JSON field names read by the provider. buyProxy returns a proxy port id +
# host:port + login/password creds; getBalance returns a numeric balance.
MOBILEPROXY_FIELD_ID: Final = "proxy_id"
MOBILEPROXY_FIELD_HOST: Final = "proxy_host"
MOBILEPROXY_FIELD_PORT_SOCKS: Final = "proxy_socks5_port"
MOBILEPROXY_FIELD_LOGIN: Final = "proxy_login"
MOBILEPROXY_FIELD_PASSWORD: Final = "proxy_pass"
MOBILEPROXY_FIELD_EXPIRES_AT: Final = "expires_at"
MOBILEPROXY_FIELD_BALANCE: Final = "balance"

# Out-of-stock signal on a 200 buyProxy body: the provider reports no port is
# currently available (transient → map to ProxyUnavailableError, caller backs off, no
# failed row). The exact wire value is partly unverified publicly (confirmed on the free
# 2h trial at the final gate, like the other MOBILEPROXY_FIELD_* below) — a documented
# guess: a `status` field equal to `"no_proxy_available"`. Named so the trial can adjust
# it without touching mobileproxy.py. Mirrors SMSPVA's get_number response=2 (out of stock).
MOBILEPROXY_STATUS_FIELD: Final = "status"
MOBILEPROXY_STATUS_NO_STOCK: Final = "no_proxy_available"

# The proxy URI scheme — SOCKS5 (Telethon/MTProto-over-SOCKS5; see research).
MOBILEPROXY_PROXY_SCHEME: Final = "socks5"

# httpx client timeout for Mobileproxy.space calls (seconds) — mirrors SMSPVA.
MOBILEPROXY_HTTP_TIMEOUT_SECONDS: Final = 15.0

# httpx 2xx success band (mirrors SMSPVA_HTTP_OK_*).
MOBILEPROXY_HTTP_OK_FLOOR: Final = 200
MOBILEPROXY_HTTP_OK_CEIL: Final = 300
# Auth-rejection status band (401 Unauthorized / 403 Forbidden) → ProxyProviderAuthError.
MOBILEPROXY_HTTP_UNAUTHORIZED: Final = 401
MOBILEPROXY_HTTP_FORBIDDEN: Final = 403

# --- FakeProxyProvider deterministic fixtures (TASK-139, CI-safe, no network). The
# fake builds a `socks5://user:pass@host:port` lease from these + a monotonic counter
# so allocate is deterministic but lease ids are unique within a provider instance. ---
FAKE_PROXY_SCHEME: Final = MOBILEPROXY_PROXY_SCHEME
FAKE_PROXY_HOST: Final = "127.0.0.1"
FAKE_PROXY_PORT: Final = 1080
FAKE_PROXY_LOGIN: Final = "fake-user"
FAKE_PROXY_PASSWORD: Final = "fake-pass"
FAKE_PROXY_LEASE_ID_PREFIX: Final = "fake-proxy-"
FAKE_PROXY_DEFAULT_BALANCE: Final = "100.00"

# --- Factory orchestration (TASK-134, Layer B1+B4+B5). The single beat task plus its
# named defaults (CONVENTIONS: no magic literals — budget/probation/interval/price). ---

# Celery task name for the factory tick (mirrors collector.constants.COLLECT_TICK_TASK).
FACTORY_TICK_TASK: Final = "factory.tasks.factory_tick"

# Default warm-up (probation) window before a registered account may be promoted into
# the live pool — 14 days (env-overridable via ACCOUNT_FACTORY_PROBATION_DAYS).
ACCOUNT_FACTORY_PROBATION_DAYS_DEFAULT: Final = 14

# Default beat interval for the factory tick (seconds). 3600 = once per hour: pool
# top-up + promotion is a slow control loop, not a hot path.
FACTORY_TICK_INTERVAL_SECONDS_DEFAULT: Final = 3600

# Default budgeted cost per provisioned number (USD). The provider/registrar surface
# carries no per-number price (PurchasedNumber has no price field), so the factory
# stamps `cost_usd` with this configured value — the figure the budget hard-cap checks
# and `total_spent_usd` accumulates. Env-overridable via ACCOUNT_FACTORY_PRICE_USD.
ACCOUNT_FACTORY_PRICE_USD_DEFAULT: Final = "1.00"

# Default budgeted cost per dynamically-allocated proxy lease (USD). Added to the row's
# `cost_usd` (number_price + proxy_price) ONLY when a proxy was allocated/assigned, so the
# budget hard-cap stays exact with no new counter. Default $0 → no budget change for the
# static-pool / no-provider paths. Env-overridable via ACCOUNT_FACTORY_PROXY_PRICE_USD.
ACCOUNT_FACTORY_PROXY_PRICE_USD_DEFAULT: Final = "0"

# Default country for the factory's buy_number calls — reuses the SMSPVA default (RU).
ACCOUNT_FACTORY_COUNTRY_DEFAULT: Final = SMSPVA_DEFAULT_COUNTRY

# Number of trailing phone digits kept visible when masking before persistence
# (e.g. `+7******1234`); the full number is NEVER persisted or logged.
FACTORY_PHONE_MASK_VISIBLE_SUFFIX: Final = 4
# Minimum digits a number must have to mask with a visible suffix; shorter numbers are
# fully starred (defensive — real MSISDNs are far longer).
FACTORY_PHONE_MASK_MIN_LEN: Final = 6

# Display-label prefix for a promoted factory session in `pool_sessions` (non-secret).
FACTORY_POOL_LABEL_PREFIX: Final = "factory-"

# --- New-account sign_up profile (TASK-133 follow-up). A freshly-bought number is NOT
# yet a Telegram account → `sign_in` raises PhoneNumberUnoccupied and the registrar must
# `sign_up` with a first name. Names are cosmetic (owner: "не суть важно"); picked
# DETERMINISTICALLY from the phone so a retry of the same number is stable. ---
FACTORY_SIGNUP_FIRST_NAMES: Final = (
    "Alex",
    "Sam",
    "Jordan",
    "Casey",
    "Riley",
    "Jamie",
    "Taylor",
    "Morgan",
    "Robin",
    "Quinn",
)
# Last name kept empty — a single given name is a valid Telegram profile and minimises
# fingerprint surface across the pool.
FACTORY_SIGNUP_LAST_NAME: Final = ""

# --- Pre-promote health probe (TASK-141, Layer B-proxy). The honest gate reads a public
# channel through the account's OWN session+proxy before promotion. ---
# Number of messages the probe fetches from the public channel; ≥1 read → healthy. One
# message is the minimal honest "can-read" proof (a gentle warm-up touch over the proxy).
FACTORY_HEALTH_READ_LIMIT: Final = 1
# A well-known public channel handle, documented as an opt-in default for
# `account_factory_health_probe_channel` (the config default stays EMPTY → fake-pass, so
# a misconfig can't blackhole promotion; an operator sets the env to enable the real read).
FACTORY_HEALTH_PROBE_CHANNEL_SUGGESTED: Final = "@telegram"
