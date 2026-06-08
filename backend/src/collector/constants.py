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
