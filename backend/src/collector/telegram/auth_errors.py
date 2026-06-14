"""Classify Telethon auth errors as PERMANENT (session dead) vs transient (TASK-087).

Telethon error types are matched STRUCTURALLY by class name across the MRO — the
same lazy approach as `reader._flood_wait_seconds` (the SDK is imported only when
present) so this module stays import-clean in pure-unit contexts and never requires
telethon at import time.

A permanent auth error means the session string is dead and will NEVER recover by
retrying: the account must be quarantined out of the pool and the owner must
re-mint that session. Retrying re-reads the same dead session every tick — the
AuthKeyDuplicated alert-spam root cause (TASK-087, ФАЗА 0).
"""

from typing import Final

# Permanent (non-recoverable) Telegram auth failures, by SPECIFIC class name:
#   * AuthKeyDuplicatedError — one session used by two clients at once; Telegram
#     PERMANENTLY invalidates the key (the prod alert-spam root cause).
#   * AuthKeyError / AuthKeyUnregisteredError / AuthKeyInvalidError — key not
#     registered / revoked / invalid.
#   * SessionRevokedError / SessionExpiredError — session killed server-side.
#   * UserDeactivatedError / UserDeactivatedBanError — account banned/deleted.
#
# DELIBERATELY NOT the telethon BASE `UnauthorizedError` (code 401): quarantine is
# PERMANENT (no recovery until the worker restarts + the owner re-mints), so we
# only evict on UNAMBIGUOUSLY dead-session classes. A bare/unknown 401 (e.g. a
# transient reconnect race) falls through to the transient path — a throttled
# `auth_error` alert, NO eviction — which is the safe, recoverable failure mode.
# Matching is still MRO-wide, so a telethon SUBCLASS of any listed error is caught.
_PERMANENT_AUTH_ERROR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "AuthKeyDuplicatedError",
        "AuthKeyError",
        "AuthKeyUnregisteredError",
        "AuthKeyInvalidError",
        "SessionRevokedError",
        "SessionExpiredError",
        "UserDeactivatedError",
        "UserDeactivatedBanError",
    }
)


def is_permanent_auth_error(error: BaseException) -> bool:
    """True iff `error` is a permanent Telegram auth failure (dead session).

    Matched by SPECIFIC class name across the full MRO (so a telethon subclass of a
    listed error is caught) without importing telethon at module load. A FLOOD_WAIT
    (transient), a bare `UnauthorizedError`, or a network/generic error returns
    False — only unambiguously dead-session classes trigger permanent eviction.
    """
    return any(klass.__name__ in _PERMANENT_AUTH_ERROR_NAMES for klass in type(error).__mro__)
