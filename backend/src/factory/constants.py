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
# Last-error diagnostic message (non-secret) recorded on a failed/banned transition.
FACTORY_LAST_ERROR_MAX: Final = 512

# --- Provider selection (TASK-133). Chooses the SmsProvider/TelegramRegistrar impl
# from env `ACCOUNT_FACTORY_PROVIDER`; default `fake` keeps CI/this env network-free. ---
ACCOUNT_FACTORY_PROVIDER_FAKE: Final = "fake"
ACCOUNT_FACTORY_PROVIDER_SMSPVA: Final = "smspva"

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
