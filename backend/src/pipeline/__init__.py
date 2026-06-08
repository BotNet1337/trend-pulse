"""Pipeline orchestration seam (Celery tasks + per-user batch locks).

This package holds the task/queue/lock *contracts* (ADR-002, task-006). Real
pipeline processing (task-007) and the scorer formulas (task-008) plug into the
seams defined here; nothing in this package mutates ORM state directly and all
Celery task arguments are JSON-serializable ids (CONVENTIONS).
"""
