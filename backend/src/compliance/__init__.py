"""Compliance domain (task-011): retention sweep + GDPR account deletion.

Public surface (CONVENTIONS: cross-module via service functions):
- `purge_expired_raw_content(session)` — NULL raw `posts.text` past the 48h window.
- `delete_user(session, user_id)` — single cascading DELETE for GDPR erasure.
- `PURGE_EXPIRED_RAW_CONTENT_TASK` — beat task name (import-cycle-free).
"""

from compliance.account import delete_user
from compliance.constants import PURGE_EXPIRED_RAW_CONTENT_TASK
from compliance.retention import purge_expired_raw_content

__all__ = [
    "PURGE_EXPIRED_RAW_CONTENT_TASK",
    "delete_user",
    "purge_expired_raw_content",
]
