"""Pydantic boundary models for the cases API (TASK-045).

CaseItem — aggregate-only projection of one proof-of-speed case.
  Contains ONLY sanitized title and metrics: no raw content, no internal IDs.

CasesResponse — top-level response envelope.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CaseItem(BaseModel):
    """Aggregate projection of one proof-of-speed case — aggregate fields only.

    Fields:
        title:              Sanitized display label (sanitize_topic_label applied).
        viral_score:        Composite virality score at fixation time.
        first_seen:         UTC timestamp when the cluster was first detected.
        mainstream_at:      UTC timestamp when the topic appeared in mainstream media
                            (operator-filled). Always NOT NULL in responses (cases
                            without mainstream_at are hidden from this endpoint).
        lead_time_seconds:  Computed: (mainstream_at - first_seen) in whole seconds.
                            Positive means we detected the trend before mainstream media.
        channels_count:     Number of source channels in the cluster at fixation
                            time (real count from scores.channels_count).

    Deliberately absent (security §5.5 / compliance §7):
        - id (internal PK — not exposed)
        - raw topic text, post content, channel handles, URLs
        - created_at (internal audit field)
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    viral_score: float
    first_seen: datetime
    mainstream_at: datetime
    lead_time_seconds: int
    channels_count: int


class CasesResponse(BaseModel):
    """Response envelope for GET /cases."""

    model_config = ConfigDict(extra="forbid")

    items: list[CaseItem]
