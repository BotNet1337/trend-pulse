"""Pydantic boundary models for the trending API (TASK-039).

TrendingItem — aggregate-only projection of one viral cluster from the showcase
tenant. Contains ONLY topic-label and metrics: no raw post text, no channel names,
no URLs (compliance §7 — TrendPulse does not sell raw content).

TrendingResponse — top-level response envelope:
  items:       list of TrendingItem sorted by viral_score desc
  warming_up:  True when the showcase tenant does not exist OR has zero clusters
               at all (regardless of pack/window). This signals the frontend to
               show «собираем сигналы…» instead of an error.
               False when showcase IS warmed (has at least one cluster), even if
               the specific pack/window has no items.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrendingItem(BaseModel):
    """Aggregate projection of one viral cluster — aggregate fields only.

    Fields:
      topic:          Sanitized display label derived from the cluster centroid
                      (cluster.topic). URLs, @-handles, and email addresses are
                      stripped at the API boundary; length is capped to
                      TRENDING_LABEL_MAX_LEN (80) characters (compliance §7, AC5).
      viral_score:    Composite virality score (score.viral_score).
      channels_count: Number of channels contributing to this cluster.
      first_seen:     UTC timestamp when the cluster was first detected.

    Deliberately absent (compliance §7):
      - post text, message content, channel handles, URLs, raw metadata.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str
    viral_score: float
    channels_count: int
    first_seen: datetime


class TrendingResponse(BaseModel):
    """Response envelope for GET /trending.

    warming_up semantics:
      True  — showcase tenant absent OR has no clusters at all (fresh deploy).
              Frontend shows «собираем сигналы…» state.
      False — showcase tenant exists AND has at least one cluster. The items list
              may still be empty (e.g. no activity for the requested pack in the
              last 24h) — this is honest data, not a warming-up state.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[TrendingItem]
    warming_up: bool
