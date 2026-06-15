"""Scorer module (task-008): pure viral-score formula + the per-user scoring tick.

`score.py` is the platform-independent pure compute (overview §4); `tasks.py`
holds `score_recent_clusters`, the body the Celery seam `pipeline.tasks.score_tick`
(task-006) delegates to.

`score_recent_clusters` is exported LAZILY (PEP 562 ``__getattr__``): importing the
pure path (`from scorer.score import compute_viral_score`, or `scorer.viral_model`)
must NOT drag in `scorer.tasks` -> billing -> storage -> config, which requires prod
secrets and a DB engine. Only `scorer.score_recent_clusters` (the task layer) triggers
that import — keeping the pure compute test-light and usable offline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scorer.score import ScoreInputs, compute_viral_score

if TYPE_CHECKING:
    from scorer.tasks import score_recent_clusters

__all__ = [
    "ScoreInputs",
    "compute_viral_score",
    "score_recent_clusters",
]


def __getattr__(name: str) -> object:
    """Lazily resolve the heavy task-layer export on first access (PEP 562)."""
    if name == "score_recent_clusters":
        from scorer.tasks import score_recent_clusters

        return score_recent_clusters
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
