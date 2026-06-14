"""PURE mapping: Reddit submission -> normalized `RawPost` (TASK-092, AC2).

No network, no mutation, no httpx import — we read attributes structurally so the
function is testable on a plain stub. External Reddit data is untrusted: every
field is normalized (tz-aware UTC, integer metrics defaulting to 0 — never `None`,
since the scorer expects numbers).

Metric mapping (runbook §Reddit-spec):
  score (ups)          -> reactions
  num_crossposts       -> forwards
  (no views)           -> views = 0   (Reddit does not expose impressions in the API)
  num_comments / upvote_ratio*100 / total_awards_received -> extra (named int counts)

`external_id` is the post fullname (`t3_…`, stable); `posted_at` is `created_utc`.
"""

from datetime import UTC, datetime
from typing import Protocol

from collector.base import PostMetrics, RawPost, SourceRef


class RedditSubmission(Protocol):
    """Structural view of the Reddit submission attributes the mapper reads.

    Members are read-only properties so an immutable (frozen) DTO like
    `client._Submission` structurally satisfies the protocol. `external_id` is the
    `t3_…` fullname; `title`/`selftext` form the post text; `score` is ups,
    `num_crossposts` shares, plus comment/ratio/awards counts; `author` is the
    poster's username.
    """

    @property
    def external_id(self) -> str: ...
    @property
    def title(self) -> str | None: ...
    @property
    def selftext(self) -> str | None: ...
    @property
    def created_utc(self) -> datetime | None: ...
    @property
    def author(self) -> str | None: ...
    @property
    def score(self) -> int: ...
    @property
    def num_crossposts(self) -> int: ...
    @property
    def num_comments(self) -> int: ...
    @property
    def upvote_ratio(self) -> float: ...
    @property
    def total_awards_received(self) -> int: ...


def _as_int(value: object) -> int:
    """Coerce an optional count to a non-negative int (missing/invalid -> 0)."""
    if isinstance(value, bool):  # bool is an int subclass — exclude explicitly
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _upvote_ratio_pct(value: object) -> int:
    """Reddit `upvote_ratio` (0.0..1.0 float) -> integer percent 0..100."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, min(100, round(float(value) * 100)))
    return 0


def _utc(value: datetime | None) -> datetime:
    """Return a tz-aware UTC datetime; naive input is assumed UTC."""
    if value is None:
        return datetime.now(tz=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(title: str | None, selftext: str | None) -> str:
    """Combine title + selftext into the post text (title is the key viral signal)."""
    parts = [p for p in (title, selftext) if p]
    return "\n\n".join(parts)


def map_submission(submission: RedditSubmission, source: SourceRef) -> RawPost:
    """Map one Reddit submission to a normalized `RawPost` (pure)."""
    return RawPost(
        source=source,
        external_id=str(submission.external_id),
        author=submission.author,
        text=_text(submission.title, submission.selftext),
        media_hashes=(),
        metrics=PostMetrics(
            views=0,  # Reddit does not expose impressions in the public API
            forwards=_as_int(submission.num_crossposts),
            reactions=_as_int(submission.score),
            extra={
                "num_comments": _as_int(submission.num_comments),
                "upvote_ratio_pct": _upvote_ratio_pct(submission.upvote_ratio),
                "total_awards_received": _as_int(submission.total_awards_received),
            },
        ),
        posted_at=_utc(submission.created_utc),
    )
