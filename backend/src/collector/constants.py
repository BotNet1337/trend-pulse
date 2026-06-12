"""Named constants for the collector (CONVENTIONS: no magic literals; time in seconds)."""

from typing import Final

# Raw-post buffer retention. Compliance cap is 48h (overview §7, ADR-002 §4); we
# keep it AT the cap. Raw content never lives longer than this anywhere.
_RAW_POST_TTL_HOURS: Final = 48
RAW_POST_TTL_SECONDS: Final = _RAW_POST_TTL_HOURS * 60 * 60  # 172800

# FLOOD_WAIT exponential backoff bounds (seconds). When Telegram does not supply a
# wait hint we grow base*2**attempt, capped, before retrying / rotating accounts.
BACKOFF_BASE_SECONDS: Final = 2
BACKOFF_CAP_SECONDS: Final = 300

# Technical-account pool size bounds. Target is 3..10 technical accounts
# (overview §2); POOL_MIN is set to 1 for now (early bootstrap with a single
# dev account) — raise back to 3 once the full pool is provisioned.
POOL_MIN: Final = 1
POOL_MAX: Final = 10

# Small courtesy delay between per-channel requests to stay under rate limits.
INTER_REQUEST_SLEEP_SECONDS: Final = 0.5

# --- collect-tick (beat ingest task) — import-cycle-free contract constants. ---
# Celery task name for the collect tick. Lives here (not in collector.tasks,
# which imports celery_app) so `scheduler` can reference it without a circular
# import — same pattern as alerts/compliance/observability constants. The task
# is unrouted → it lands on the default `celery` queue the worker consumes.
COLLECT_TICK_TASK: Final = "collector.tasks.collect_tick"
# Redis key holding the start time (UTC ISO) of the last successful collect
# pass — the next tick's `since` lower bound, so the same window is not
# re-read forever (buffer+pipeline dedup handles the residual overlap).
COLLECT_LAST_TICK_KEY: Final = "collect:last_tick_at"
