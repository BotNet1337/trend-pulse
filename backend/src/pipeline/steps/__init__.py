"""Pure, immutable, platform-independent pipeline steps (task-007, ADR-001).

Each step exposes ``run(...)`` taking a list and returning a NEW list of new
objects — inputs are never mutated. Steps operate only on the `RawPost` /
`NormalizedPost` contracts (ADR-001) and import nothing from `collector/telegram/*`,
so the whole chain stays platform-independent (AC7). The heavy embedding model is
loaded lazily inside `embed` (never at import — keeps the api/import path light).
"""

from pipeline.steps import cluster, dedup, embed, normalize
from pipeline.steps.cluster import ClusterCandidate
from pipeline.steps.normalize import NormalizedPost

__all__ = [
    "ClusterCandidate",
    "NormalizedPost",
    "cluster",
    "dedup",
    "embed",
    "normalize",
]
