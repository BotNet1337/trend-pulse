"""Scorer module (task-008): pure viral-score formula + the per-user scoring tick.

`score.py` is the platform-independent pure compute (overview §4); `tasks.py`
holds `score_recent_clusters`, the body the Celery seam `pipeline.tasks.score_tick`
(task-006) delegates to. Importing `compute_viral_score` does not require Celery —
the pure path stays test-light — but the package also re-exports
`score_recent_clusters` for the task layer.
"""

from scorer.score import ScoreInputs, compute_viral_score
from scorer.tasks import score_recent_clusters

__all__ = [
    "ScoreInputs",
    "compute_viral_score",
    "score_recent_clusters",
]
