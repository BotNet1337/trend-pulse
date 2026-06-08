"""Domain errors for the collector (CONVENTIONS: explicit errors, no bare except)."""


class CollectorError(Exception):
    """Base class for all collector domain errors."""


class PoolConfigError(CollectorError):
    """Account-pool misconfiguration (missing creds, size outside POOL_MIN..POOL_MAX)."""


class SourceUnavailableError(CollectorError):
    """A source could not be read (private/removed/renamed) — skip it, keep the rest."""


class AllAccountsFloodWaitError(CollectorError):
    """Every pool account is cooling down under FLOOD_WAIT; caller should back off."""


class BufferWriteError(CollectorError):
    """A raw post could not be written to the Redis buffer (not silently dropped)."""
