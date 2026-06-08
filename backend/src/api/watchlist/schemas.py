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
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from storage.models.channels import SourceKind

# Telegram public handle: leading '@' + 4..32 of [A-Za-z0-9_] (Telegram username
# rules). Real existence check is the collector's job (task-005); this is the
# format gate at the API boundary.
TELEGRAM_HANDLE_PATTERN = re.compile(r"^@[A-Za-z0-9_]{4,32}$")

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

    @field_validator("handle")
    @classmethod
    def _validate_handle(cls, value: str) -> str:
        if not TELEGRAM_HANDLE_PATTERN.match(value):
            raise ValueError("handle must match a Telegram username: '@' + 4-32 of [A-Za-z0-9_]")
        return value


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


class WatchlistRead(BaseModel):
    """Response model: the persisted watchlist row, tenant id included (AC1)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: int
    topic: str
    channel: ChannelRef
    alert_config: AlertConfig
