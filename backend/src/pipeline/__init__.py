"""Pipeline orchestration seam (Celery tasks + per-user batch locks) + body.

This package holds the task/queue/lock *contracts* (ADR-002, task-006) and the
pure pipeline body (task-007): the `steps` chain (dedup → normalize → embed →
cluster) plus `process_user_batch`. Nothing here mutates ORM state implicitly and
all Celery task arguments are JSON-serializable ids (CONVENTIONS). `tasks` is NOT
re-exported from this package init so importing `pipeline` stays free of the
Celery app on the light (api) import path; import `pipeline.tasks` explicitly.
"""

from pipeline.batch_processor import process_user_batch

__all__ = ["process_user_batch"]
