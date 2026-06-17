"""Pydantic boundary models for the watchlist API (CONVENTIONS: validate at edge).

User decision (overrides the task doc's multi-channel `channels: list` shape):
ONE DB row = ONE watchlist = one `(user_id, channel_id, topic)` + alert-config.
A watchlist therefore carries a SINGLE channel and is addressed by its numeric
row id. To watch the same topic across several channels the user POSTs once per
channel (multiple separate watchlists).

`min_channels` is a SCORING parameter (the cross-channel alert threshold used by
task-006/008), NOT the count of channels in this watchlist — so the task doc edge
case "min_channels > number of channels" does not apply here.

All ranges/defaults/regex are named module constants — no magic literals.
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from storage.models.channels import SourceKind

# Telegram public handle: leading '@' + 4..32 of [A-Za-z0-9_] (Telegram username
# rules). Real existence check is the collector's job (task-005); this is the
# format gate at the API boundary.
TELEGRAM_HANDLE_PATTERN = re.compile(r"^@[A-Za-z0-9_]{4,32}$")

# Twitter/X handle: a username of 1..15 of [A-Za-z0-9_], optional leading '@'
# (TASK-031). The collector normalizes the '@' away; real existence is the
# collector's validate_ref job — this is just the boundary format gate.
TWITTER_HANDLE_PATTERN = re.compile(r"^@?[A-Za-z0-9_]{1,15}$")

# Reddit handle: a subreddit name of 3..21 of [A-Za-z0-9_], optional leading 'r/'
# (TASK-092). The collector normalizes the 'r/' away; real existence is the
# collector's validate_ref job — this is just the boundary format gate.
REDDIT_HANDLE_PATTERN = re.compile(r"^(?:r/)?[A-Za-z0-9_]{3,21}$")

# Per-source handle format gate (selected by `ChannelRef.kind`).
_HANDLE_PATTERN_BY_KIND = {
    SourceKind.TELEGRAM: TELEGRAM_HANDLE_PATTERN,
    SourceKind.TWITTER: TWITTER_HANDLE_PATTERN,
    SourceKind.REDDIT: REDDIT_HANDLE_PATTERN,
}

# Per-source human-readable error for an ill-formatted handle.
_HANDLE_ERROR_BY_KIND = {
    SourceKind.TELEGRAM: "handle must match a Telegram username: '@' + 4-32 of [A-Za-z0-9_]",
    SourceKind.TWITTER: (
        "handle must match a Twitter username: 1-15 of [A-Za-z0-9_] (optional leading '@')"
    ),
    SourceKind.REDDIT: (
        "handle must match a subreddit name: 3-21 of [A-Za-z0-9_] (optional leading 'r/')"
    ),
}

# Alert-config ranges (scoring contract; full scorer is task-006/008).
SCORE_THRESHOLD_MIN = 0
SCORE_THRESHOLD_MAX = 100
MIN_CHANNELS_MIN = 1

# ISO-639-1 two-letter lowercase language code; default notification language.
ISO_639_1_PATTERN = re.compile(r"^[a-z]{2}$")
DEFAULT_NOTIFICATION_LANG = "en"

TOPIC_MAX_LEN = 255


class ChannelRef(BaseModel):
    """A single source reference: a platform `kind` + its `handle` (ADR-001)."""

    model_config = ConfigDict(extra="forbid")

    handle: str
    kind: SourceKind = SourceKind.TELEGRAM

    @model_validator(mode="after")
    def _validate_handle_for_kind(self) -> "ChannelRef":
        # Validate the handle against the pattern for its source kind (TASK-031).
        # A model-validator (not field-validator) is used because the rule depends
        # on `kind`; Telegram behaviour is unchanged (backward-compat).
        pattern = _HANDLE_PATTERN_BY_KIND.get(self.kind)
        if pattern is None:
            raise ValueError(f"unsupported source kind: {self.kind!r}")
        if not pattern.match(self.handle):
            raise ValueError(_HANDLE_ERROR_BY_KIND[self.kind])
        return self


class AlertConfig(BaseModel):
    """Per-watchlist alert tuning (maps to Watchlist.threshold/min_channels/lang)."""

    model_config = ConfigDict(extra="forbid")

    score_threshold: Annotated[int, Field(ge=SCORE_THRESHOLD_MIN, le=SCORE_THRESHOLD_MAX)]
    min_channels: Annotated[int, Field(ge=MIN_CHANNELS_MIN)]
    notification_lang: str = DEFAULT_NOTIFICATION_LANG

    @field_validator("notification_lang")
    @classmethod
    def _validate_lang(cls, value: str) -> str:
        if not ISO_639_1_PATTERN.match(value):
            raise ValueError("notification_lang must be a 2-letter lowercase ISO-639-1 code")
        return value


class WatchlistCreate(BaseModel):
    """Create payload: one topic + one channel + alert-config -> one watchlist row."""

    model_config = ConfigDict(extra="forbid")

    topic: Annotated[str, Field(min_length=1, max_length=TOPIC_MAX_LEN)]
    channel: ChannelRef
    alert_config: AlertConfig


class WatchlistUpdate(BaseModel):
    """Partial update: only supplied fields are applied (PATCH, `exclude_unset`)."""

    model_config = ConfigDict(extra="forbid")

    topic: Annotated[str, Field(min_length=1, max_length=TOPIC_MAX_LEN)] | None = None
    channel: ChannelRef | None = None
    alert_config: AlertConfig | None = None


class WatchlistSignal(BaseModel):
    """Live signal for a watchlist row on the Signal Desk (TASK-096).

    Aggregated read-only from the `Score` / `Alert` rows of the clusters the
    watchlist's channel participates in (channel-overlap join, TASK-084). Every
    field is graceful: `None` / empty when there is genuinely no data — never
    fabricated (INV2).

    - `live_velocity` — latest in-window `Score.velocity` (∈ [0, 1] normalized
      cross-channel burst), `None` when no in-window score.
    - `live_score` — latest in-window `Score.viral_score` (0-100), `None` when none.
    - `sparkline_24h` — hourly max `viral_score` over the last 24h, oldest→newest;
      empty when no in-window scores.
    - `last_alert_at` — most recent alert's `first_seen`, `None` when no alert.
    - `effective_sources` — `exp(source-entropy)` of the latest in-window score
      (TASK-126): the effective number of independent sources (single-source
      amplification collapses to ~1.0). An organic-spread / independence signal,
      NOT a coordination verdict; pair with synchrony/similarity-null next. `None`
      when there is no in-window score or the score predates the migration.
    """

    model_config = ConfigDict(extra="forbid")

    live_velocity: float | None = None
    live_score: float | None = None
    sparkline_24h: list[float] = Field(default_factory=list)
    last_alert_at: datetime | None = None
    effective_sources: float | None = None


class WatchlistRead(BaseModel):
    """Response model: the persisted watchlist row, tenant id included (AC1).

    `signal` (TASK-096) carries the live virality signal for the row's channel —
    always present, graceful-empty when there is no data.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: int
    topic: str
    channel: ChannelRef
    alert_config: AlertConfig
    signal: WatchlistSignal = Field(default_factory=WatchlistSignal)
