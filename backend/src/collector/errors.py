"""Domain errors for the collector (CONVENTIONS: explicit errors, no bare except)."""


class CollectorError(Exception):
    """Base class for all collector domain errors."""


class PoolConfigError(CollectorError):
    """Account-pool misconfiguration (missing creds, size outside POOL_MIN..POOL_MAX)."""


class SourceUnavailableError(CollectorError):
    """A source could not be read (private/removed/renamed) — skip it, keep the rest."""


class AllAccountsFloodWaitError(CollectorError):
    """Every pool account is cooling down under FLOOD_WAIT; caller should back off."""


class PoolExhaustedError(CollectorError):
    """Every pool account is quarantined (dead sessions) — re-mint required (TASK-087).

    Distinct from `AllAccountsFloodWaitError`: cooling accounts recover after their
    cooldown, quarantined ones never do. The reader must NOT retry/sleep on this —
    the tick skips the ref (like SourceUnavailableError) until sessions are re-minted.
    """


class BufferWriteError(CollectorError):
    """A raw post could not be written to the Redis buffer (not silently dropped)."""
