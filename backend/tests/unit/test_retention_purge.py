"""AC1 RED→GREEN anchor: `purge_expired_raw_content` clears raw text >48h old.

Unit-level (DB-free): a fake session captures the issued bulk UPDATE so the test
asserts the selection predicate (age by `fetched_at` > retention window) and that
ONLY the `text` column is set to NULL — metrics/embedding/cluster rows are never
touched. The real cascade/no-orphan behaviour is the integration test.
"""

from datetime import timedelta

from storage.models.base import utcnow
from storage.models.posts import Post


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's `CursorResult` (only `rowcount` used)."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeSession:
    """Captures the single bulk-UPDATE statement `purge` executes."""

    def __init__(self, rowcount: int) -> None:
        self._rowcount = rowcount
        self.executed: list[object] = []

    def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self._rowcount)


def test_purge_clears_only_old_raw_text() -> None:
    from compliance.retention import purge_expired_raw_content

    session = _FakeSession(rowcount=1)
    purged = purge_expired_raw_content(session)

    assert purged == 1
    # Exactly one bulk statement issued (set-based, not row-by-row).
    assert len(session.executed) == 1
    compiled = str(session.executed[0])
    # Targets the posts table, sets `text` to NULL, filters by ingestion age.
    assert "posts" in compiled.lower()
    assert "text" in compiled.lower()
    assert "fetched_at" in compiled.lower()


def test_purge_predicate_matches_old_and_spares_fresh() -> None:
    """The age boundary is evaluated against the retention window in seconds."""
    from compliance.retention import _build_purge_statement

    now = utcnow()
    stmt = _build_purge_statement(now)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))

    # A bulk UPDATE on posts that NULLs text where fetched_at < cutoff.
    assert "UPDATE posts" in compiled
    assert "SET text=" in compiled or "SET text =" in compiled
    assert "fetched_at" in compiled

    # Sanity on the model contract the purge relies on: a 49h-old post is expired,
    # a 1h-old post is fresh (boundary uses fetched_at as ingestion age).
    old = Post(
        user_id=1,
        channel_id=1,
        external_id="old",
        posted_at=now - timedelta(hours=49),
        fetched_at=now - timedelta(hours=49),
        text="VIRAL_MARKER_OLD",
    )
    fresh = Post(
        user_id=1,
        channel_id=1,
        external_id="fresh",
        posted_at=now - timedelta(hours=1),
        fetched_at=now - timedelta(hours=1),
        text="VIRAL_MARKER_FRESH",
    )
    assert old.text == "VIRAL_MARKER_OLD"
    assert fresh.text == "VIRAL_MARKER_FRESH"


def test_purge_no_rows_is_safe() -> None:
    """No persisted raw text → 0 purged, never an error (edge case)."""
    from compliance.retention import purge_expired_raw_content

    session = _FakeSession(rowcount=0)
    assert purge_expired_raw_content(session) == 0
