"""Immutable corpus records + CSV-snapshot loaders for the offline harness (TASK-081).

The snapshot is a read-only export from prod (see `scripts/export_corpus.sh`): two
CSVs — `posts.csv` and `clusters.csv` — containing ONLY metrics + centroids (NO
text, which is NULL anyway → no PII/compliance concern, see CONVENTIONS retention).

Parsing validates at the boundary (CONVENTIONS: never trust external data): a row
that cannot be parsed into the expected types raises `CorpusParseError` with the
1-based row number, instead of silently coercing. The loaders are pure readers —
they touch no DB and no network.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# pgvector text representation is "[f1,f2,...]"; these are the literal delimiters.
_VECTOR_OPEN = "["
_VECTOR_CLOSE = "]"


class CorpusParseError(ValueError):
    """A snapshot row could not be parsed into the expected typed record."""


@dataclass(frozen=True)
class PostRecord:
    """One row of the posts snapshot — metrics only (text/embedding are NULL in prod)."""

    id: int
    posted_at: datetime
    channel_id: int
    user_id: int
    cluster_id: int | None
    views: int
    forwards: int
    reactions: int


@dataclass(frozen=True)
class ClusterRecord:
    """One row of the clusters snapshot — includes the 384-d centroid embedding."""

    id: int
    user_id: int
    first_seen: datetime
    updated_at: datetime
    topic: str
    centroid: tuple[float, ...]


def _parse_dt(value: str, *, row_num: int, field: str) -> datetime:
    """Parse a Postgres-CSV timestamptz string (e.g. ``2026-06-12 14:15:57+00``)."""
    text = value.strip()
    # Postgres emits "+00" / "+00:00"; datetime.fromisoformat (3.12) accepts both
    # once the space separator is normalised to "T".
    iso = text.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(iso)
    except ValueError as exc:  # pragma: no cover - exercised via load tests
        raise CorpusParseError(f"row {row_num}: bad datetime in {field!r}: {value!r}") from exc


def _parse_int(value: str, *, row_num: int, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise CorpusParseError(f"row {row_num}: bad int in {field!r}: {value!r}") from exc


def _parse_optional_int(value: str) -> int | None:
    return None if value == "" else int(value)


def parse_centroid(value: str, *, row_num: int = 0) -> tuple[float, ...]:
    """Parse a pgvector text literal ``[f1,f2,...]`` into a float tuple.

    Exposed (not ``_``-prefixed) so the clustering audit and its tests can construct
    centroids from the same canonical representation.
    """
    text = value.strip()
    if not (text.startswith(_VECTOR_OPEN) and text.endswith(_VECTOR_CLOSE)):
        raise CorpusParseError(f"row {row_num}: centroid not a pgvector literal: {value[:32]!r}")
    inner = text[1:-1].strip()
    if not inner:
        raise CorpusParseError(f"row {row_num}: empty centroid")
    try:
        return tuple(float(part) for part in inner.split(","))
    except ValueError as exc:
        raise CorpusParseError(f"row {row_num}: non-float in centroid") from exc


def load_posts(path: Path) -> list[PostRecord]:
    """Load the posts snapshot CSV into immutable `PostRecord`s (header required)."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            PostRecord(
                id=_parse_int(row["id"], row_num=n, field="id"),
                posted_at=_parse_dt(row["posted_at"], row_num=n, field="posted_at"),
                channel_id=_parse_int(row["channel_id"], row_num=n, field="channel_id"),
                user_id=_parse_int(row["user_id"], row_num=n, field="user_id"),
                cluster_id=_parse_optional_int(row["cluster_id"]),
                views=_parse_int(row["views"], row_num=n, field="views"),
                forwards=_parse_int(row["forwards"], row_num=n, field="forwards"),
                reactions=_parse_int(row["reactions"], row_num=n, field="reactions"),
            )
            for n, row in enumerate(reader, start=1)
        ]


def iter_cluster_meta(path: Path) -> Iterator[ClusterRecord]:
    """Yield `ClusterRecord`s lazily (centroids are large — 384 floats x 9.4k rows).

    Lazy iteration keeps peak memory bounded for callers that only need one pass
    (e.g. topic-duplicate counting); the centroid audit materialises a numpy matrix
    separately via `load_centroid_matrix`.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for n, row in enumerate(reader, start=1):
            yield ClusterRecord(
                id=_parse_int(row["id"], row_num=n, field="id"),
                user_id=_parse_int(row["user_id"], row_num=n, field="user_id"),
                first_seen=_parse_dt(row["first_seen"], row_num=n, field="first_seen"),
                updated_at=_parse_dt(row["updated_at"], row_num=n, field="updated_at"),
                topic=row["topic"],
                centroid=parse_centroid(row["embedding"], row_num=n),
            )


def load_clusters(path: Path) -> list[ClusterRecord]:
    """Eagerly load all cluster records (convenience wrapper over `iter_cluster_meta`)."""
    return list(iter_cluster_meta(path))


def cluster_sizes(posts: Sequence[PostRecord]) -> dict[int, int]:
    """Count posts per `cluster_id`, skipping orphan posts (cluster_id is NULL)."""
    sizes: dict[int, int] = {}
    for post in posts:
        if post.cluster_id is None:
            continue
        sizes[post.cluster_id] = sizes.get(post.cluster_id, 0) + 1
    return sizes
