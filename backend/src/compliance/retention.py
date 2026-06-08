"""Raw-content retention sweep (task-011, overview §7 / ADR-002 §4).

`purge_expired_raw_content` NULLs the raw `posts.text` column for every post whose
ingestion age exceeds `RAW_CONTENT_RETENTION_SECONDS` (48h). Age is measured by
`fetched_at` — the instant the post entered OUR storage — NOT `posted_at` (when it
was published on Telegram): the 48h compliance clock starts at ingestion, and
`fetched_at` is server-set (`default=utcnow`) so it can never be spoofed by source
data. Only the `text` column is cleared; metrics (views/forwards/reactions), the
optional embedding vector, and all cluster/score rows are left intact — they are
aggregates, not raw content, and are the persistent value (overview §7).

Set-based bulk UPDATE via SQLAlchemy bind params (CONVENTIONS: never f-string SQL);
idempotent and no-op-safe (0 matching rows → returns 0, never an error).
"""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, Update, update
from sqlalchemy.orm import Session

from config import get_settings
from storage.models.base import utcnow
from storage.models.posts import Post


def _build_purge_statement(now: datetime) -> Update:
    """Build the bulk UPDATE that NULLs `text` for posts older than the window.

    The cutoff is `now - RAW_CONTENT_RETENTION_SECONDS`; rows with
    `fetched_at < cutoff` are expired. `now` is injected so callers/tests pin a
    deterministic instant (timezone-aware UTC — `fetched_at` is `timezone=True`,
    avoiding off-by-hours at the 48h boundary).
    """
    retention_seconds = get_settings().raw_content_retention_seconds
    cutoff = now - timedelta(seconds=retention_seconds)
    return (
        update(Post).where(Post.fetched_at < cutoff).where(Post.text.is_not(None)).values(text=None)
    )


def purge_expired_raw_content(session: Session) -> int:
    """Clear raw `text` for posts past the retention window; return rows purged.

    Pure-ish over the session: a single bulk UPDATE, no I/O beyond the DB. The
    caller owns the transaction boundary (commit/rollback) — see `storage.database`.
    """
    result = cast(CursorResult[object], session.execute(_build_purge_statement(utcnow())))
    return result.rowcount
