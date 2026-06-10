"""`showcase_cases` — proof-of-speed marketing case snapshots (TASK-045).

Schema decision — topic vs title
---------------------------------
The locate phase confirmed: ``Cluster.topic`` is raw post text (post.text[:255]),
not a keyword.  There is no separate "watchlist-style topic" available at fixation
time.  Storing a ``topic`` column alongside ``title`` would make them identical
(both sanitized from the same raw field), adding no information value.

Decision: store ONE sanitized label column named ``title``.  ``title`` holds the
output of ``textutils.sanitize_topic_label(cluster.topic)`` — URLs, @-handles, and
email addresses stripped, whitespace collapsed, capped to TOPIC_LABEL_MAX_LEN.

UNIQUE dedup: ``(title, first_seen)`` — a case is unique by sanitized label + the
moment it was first detected.  Two clusters with the same sanitized label but
detected on different days produce two rows (as intended: different events).

Compliance invariant:
  ``cases live months; raw post text has 48h retention.``
  → NO raw ``cluster.topic`` text must be stored here.
  → ONLY ``sanitize_topic_label(cluster.topic)`` is persisted.

No FK to clusters/posts/scores: snapshot is self-sufficient so the case
survives the 48h retention purge of all source rows (AC3, Discussion TASK-045).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from storage.models.base import Base, utcnow
from textutils import TOPIC_LABEL_MAX_LEN

# Max column length for the sanitized title — derived from the sanitizer cap so a
# future bump of TOPIC_LABEL_MAX_LEN cannot silently overflow the column
# from textutils, plus a small buffer to accommodate the ellipsis character.
_TITLE_MAX_LEN: int = TOPIC_LABEL_MAX_LEN + 20


class ShowcaseCase(Base):
    """Proof-of-speed marketing case snapshot.

    Created when a showcase-tenant cluster first crosses the
    ``showcase_case_min_score`` threshold (default 90.0).

    Lifecycle:
      1. Beat tick calls ``showcase.cases.fix_cases()`` → INSERT with
         on_conflict_do_nothing (idempotent on unique key).
      2. Operator marks mainstream appearance: UPDATE mainstream_at = <timestamp>
         via ``make case-mainstream ID=… AT=…`` (scripts/case_mainstream.py).
      3. GET /cases returns only rows with mainstream_at IS NOT NULL, sorted by
         lead-time DESC (mainstream_at - first_seen).

    Compliance:
      - ``title`` is ALWAYS the sanitized label (textutils.sanitize_topic_label).
      - No raw cluster.topic, no post text, no channel handles anywhere.
      - No FK to retention-affected tables (clusters/posts/scores) — snapshot
        is the contract; the source data may be purged after 48h.
    """

    __tablename__ = "showcase_cases"
    __table_args__ = (
        # Dedup: same sanitized label first detected at the same instant → one row.
        UniqueConstraint("title", "first_seen", name="uq_showcase_cases_title_first_seen"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Sanitized display label — output of sanitize_topic_label(cluster.topic).
    # COMPLIANCE: never store raw cluster.topic here; only the sanitized result.
    title: Mapped[str] = mapped_column(String(_TITLE_MAX_LEN), nullable=False)

    # Aggregate metrics snapshot at fixation time.
    viral_score: Mapped[float] = mapped_column(Float, nullable=False)

    # First detection timestamp (cluster.first_seen at fixation).
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Number of channels contributing. MVP = 1; TODO: persist real count in scorer.
    channels_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Operator-filled: when this topic appeared in mainstream media.
    # NULL = not yet filled (hidden from GET /cases until set).
    mainstream_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # Row creation timestamp (auto).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
