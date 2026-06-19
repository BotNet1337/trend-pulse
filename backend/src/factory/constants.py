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
