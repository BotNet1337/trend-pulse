"""Cosine-similarity clustering (task-007 step 4, AC4).

Pure + immutable: ``run`` returns a NEW list of frozen `ClusterCandidate`s and
mutates neither the posts nor the vectors. Greedy single-link grouping — a post
joins the first existing cluster whose centroid it is within
``Settings.cluster_cosine_threshold`` of (cosine), otherwise it seeds a new
cluster. Centroids update as the mean of member vectors. Uses numpy only (core
dep) — no sklearn. Cosine on a zero/degenerate vector is guarded against division
by zero (returns 0 similarity). Platform-independent: operates on `NormalizedPost`
+ plain float vectors (ADR-001).
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from config import get_settings
from pipeline.constants import CLUSTER_TOPIC_MAX_LEN
from pipeline.steps.normalize import NormalizedPost


@dataclass(frozen=True)
class ClusterCandidate:
    """A semantic group of posts ready to persist as a `clusters` row (task-002).

    Frozen/immutable. `topic` is derived from the first member's text (capped to the
    column width); `embedding` is the centroid (mean) vector; `posts` are the member
    `NormalizedPost`s; `post_embeddings` are those members' per-post vectors, parallel
    to `posts` (the SAME vectors that drove clustering — not the centroid, not
    re-embedded); `handles` are the distinct source handles that contributed
    (cross-source aggregation, ADR-001). The batch processor maps this to a
    `Cluster` ORM row scoped by `user_id`, and persists each member `Post` carrying its
    `post_embeddings` entry (task-082: per-post vectors survive the 48h text purge).

    `post_embeddings` defaults to an empty tuple so directly-constructed candidates
    (e.g. in tests) stay valid; `run` always populates it parallel to `posts`.
    """

    topic: str
    embedding: tuple[float, ...]
    posts: tuple[NormalizedPost, ...]
    handles: tuple[str, ...]
    post_embeddings: tuple[tuple[float, ...], ...] = ()


def _cosine(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    """Cosine similarity of two vectors; 0.0 when either is degenerate (zero norm)."""
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _topic_for(post: NormalizedPost) -> str:
    """Derive a short topic label from a post's cleaned text (column-width capped)."""
    return post.text[:CLUSTER_TOPIC_MAX_LEN]


class _Group:
    """Mutable accumulator used only inside `run`; never leaks to the caller."""

    def __init__(self, post: NormalizedPost, vector: NDArray[np.float64]) -> None:
        self.posts: list[NormalizedPost] = [post]
        self.vectors: list[NDArray[np.float64]] = [vector]

    @property
    def centroid(self) -> NDArray[np.float64]:
        mean: NDArray[np.float64] = np.mean(np.stack(self.vectors), axis=0)
        return mean

    def add(self, post: NormalizedPost, vector: NDArray[np.float64]) -> None:
        self.posts.append(post)
        self.vectors.append(vector)

    def to_candidate(self) -> ClusterCandidate:
        centroid = self.centroid
        # Distinct contributing handles, first-seen order preserved.
        handles: list[str] = []
        for post in self.posts:
            handle = post.source.handle
            if handle not in handles:
                handles.append(handle)
        return ClusterCandidate(
            topic=_topic_for(self.posts[0]),
            embedding=tuple(float(value) for value in centroid),
            posts=tuple(self.posts),
            handles=tuple(handles),
            # Per-post vectors, parallel to `posts` — the same vectors used for
            # grouping, carried through so the persist step can write posts.embedding.
            post_embeddings=tuple(
                tuple(float(value) for value in vector) for vector in self.vectors
            ),
        )


def run(posts: list[NormalizedPost], vectors: list[list[float]]) -> list[ClusterCandidate]:
    """Group posts by cosine similarity ≥ threshold into `ClusterCandidate`s.

    `posts[i]` is embedded by `vectors[i]` (parallel lists, equal length required).
    Empty input → empty list. Inputs are never mutated.
    """
    if len(posts) != len(vectors):
        raise ValueError(
            f"posts/vectors length mismatch: {len(posts)} posts, {len(vectors)} vectors"
        )
    if not posts:
        return []

    threshold = get_settings().cluster_cosine_threshold
    groups: list[_Group] = []

    for post, raw_vector in zip(posts, vectors, strict=True):
        vector = np.asarray(raw_vector, dtype=np.float64)
        best_group: _Group | None = None
        best_similarity = threshold
        for group in groups:
            similarity = _cosine(vector, group.centroid)
            if similarity >= best_similarity:
                best_similarity = similarity
                best_group = group
        if best_group is None:
            groups.append(_Group(post, vector))
        else:
            best_group.add(post, vector)

    return [group.to_candidate() for group in groups]
