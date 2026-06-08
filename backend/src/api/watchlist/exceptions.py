"""Domain exceptions for the watchlist module.

The router maps these to HTTP codes (CONVENTIONS: domain errors at the service
layer, HTTP translation at the boundary):
- RefValidationError  -> 422 (bad channel reference)
- LimitExceededError  -> 402 (plan limit; full enforcement is task-010)
- DuplicateWatchlistError -> 409 (unique (user_id, channel_id, topic))
"""


class WatchlistError(Exception):
    """Base class for watchlist domain errors."""


class RefValidationError(WatchlistError):
    """A channel reference failed validation (format or collector check)."""


class LimitExceededError(WatchlistError):
    """The caller would exceed their plan's watchlist limit."""


class DuplicateWatchlistError(WatchlistError):
    """A watchlist with the same (user_id, channel_id, topic) already exists."""
