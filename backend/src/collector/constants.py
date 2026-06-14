"""Named constants for the collector (CONVENTIONS: no magic literals; time in seconds)."""

from typing import Final

# Raw-post buffer retention. Compliance cap is 48h (overview §7, ADR-002 §4); we
# keep it AT the cap. Raw content never lives longer than this anywhere.
_RAW_POST_TTL_HOURS: Final = 48
RAW_POST_TTL_SECONDS: Final = _RAW_POST_TTL_HOURS * 60 * 60  # 172800

# Max posts kept per `raw:{kind}:{handle}` buffer list (OOM safety belt, TASK-076).
# Redis is the Celery broker AND the raw-post buffer under one 256M cgroup cap; an
# undrained/hot source must not be able to fill it and trigger the kernel OOM-kill.
# On overflow the OLDEST buffered posts are dropped (recency matters for a viral
# detector) — see `buffer.write_post`. An order of magnitude above a normal tick,
# yet bounds one list to single-digit MB instead of hundreds. NOT the root fix for
# buffer growth (that is the drain bug / lookback cap) — this is the safety net.
MAX_RAW_BUFFER_LEN: Final = 50_000

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

# Hard per-tick safety cap on messages read from ONE channel (task-078/task-083).
# The reader fetches the NEWEST posts in the recent window newest-first (Telethon
# default `reverse=False`) and BREAKS once it passes `since`, see reader._read_one.
# Earlier idioms were traps: `offset_date` WITHOUT `reverse=True` is an UPPER bound
# that walked the ENTIRE history backward (task-077: prod 2026→2017 → GetHistory
# flood storms, 100k+ buffers); `reverse=True` + `offset_date` yields the OLDEST of
# the window first (cap truncates the newest) and, with no marker, Telethon forces
# `offset_id=1` → the channel's OLDEST messages (task-083: prod ingested 2024-era
# posts after a Redis flush). This cap is the backstop: it maps to Telethon's
# `iter_messages(limit=...)` so even a misconfigured `since` (huge lookback,
# corrupt-marker fallback, or `None`) can never trigger a deep full-history
# pull again. A recent window (lookback 600s, tick 60s) reads far fewer than
# this in steady state, so the cap is invisible until something is misconfigured
# — which is exactly when we want the brakes on.
MAX_MESSAGES_PER_TICK: Final = 500

# Max FLOOD_WAIT the reader is allowed to sleep INSIDE one read (seconds).
# Telethon already auto-sleeps short flood waits internally (its
# `flood_sleep_threshold`); a hint that reaches the reader can be huge
# (minutes..hours). Sleeping it in-task parked the collect-tick coroutine for
# the FLOOD_WAIT's lifetime and held a celery slot (prod hang, pool=1:
# "rotation" lands on the same cooling account). Above the cap the ref is
# aborted via `AllAccountsFloodWaitError` — the tick skips it with a warning
# and a later tick retries once the account's cooldown has elapsed.
FLOOD_WAIT_INLINE_CAP_SECONDS: Final = 60

# --- Twitter/X source (TASK-031, ADR-001) ----------------------------------
# X API 2026 is PAY-PER-USE ($0.005 per post read, 2M/mo cap) — the legacy fixed
# Basic/Pro tiers are closed to new signups. read-budget is therefore the central
# cost constraint (unlike the free Telegram MTProto pool), so the Twitter collector
# polls RARELY, fetches FEW tweets per tick, and hard-caps monthly reads.
# Research brief: docs/research/twitter-source-research-brief.md §1.

# Recommended Twitter collect cadence (seconds) — informational anchor for the
# scheduler (Twitter ticks RARELY, not every 60s like Telegram, to bound read cost).
TWITTER_COLLECT_INTERVAL_SECONDS: Final = 15 * 60  # 15 minutes

# Hard per-ref cap on tweets read from ONE account per tick. The X timeline
# endpoint allows up to 100; we keep it small because every tweet read costs money.
TWITTER_MAX_RESULTS_PER_TICK: Final = 25

# Monthly read budget (number of post reads). When the running month's reads reach
# this, the collector stops reading and alerts ops ONCE — a spend backstop so a
# misconfiguration can't run up the pay-per-use bill. Well under the 2M API cap.
MAX_TWITTER_READS_PER_MONTH: Final = 100_000

# Max 429 rate-limit wait the reader sleeps INLINE before skipping the ref
# (seconds). Above this the ref is skipped this tick (retried next tick), mirroring
# the Telegram FLOOD_WAIT inline cap — a long reset must not park the collect tick.
TWITTER_RATE_LIMIT_INLINE_CAP_SECONDS: Final = 60

# Redis key prefix for the monthly read-budget counter: twitter:reads:{YYYY-MM}.
TWITTER_READS_COUNTER_PREFIX: Final = "twitter:reads"

# Per-account minimum read interval (seconds). The shared collect tick fires every
# `collect_interval_seconds` (~60s) and reads ALL kinds; without this guard Twitter
# would be polled every tick (43 accounts x 1440 ticks/day = pay-per-use blowout).
# We read each Twitter account at most once per this window (Redis last-read stamp),
# making the 15-min cadence real regardless of the shared tick frequency.
TWITTER_MIN_READ_INTERVAL_SECONDS: Final = TWITTER_COLLECT_INTERVAL_SECONDS  # 15 min
TWITTER_LASTREAD_PREFIX: Final = "twitter:lastread"

# Cache handle → user id (resolve is itself a billable read; ids are stable). TTL
# long but bounded so renamed/deleted accounts eventually re-resolve.
TWITTER_USERID_PREFIX: Final = "twitter:userid"
TWITTER_USERID_TTL_SECONDS: Final = 7 * 24 * 60 * 60  # 7 days

# After an HTTP 402 CreditsDepleted, pause ALL Twitter reads for this long (seconds)
# and alert ops ONCE — a persistent billing state (no API credits), so retrying every
# tick just spams logs and fires rejected calls. Cleared automatically after cooldown.
TWITTER_CREDITS_COOLDOWN_SECONDS: Final = 60 * 60  # 1 hour

# --- Reddit source (TASK-092, ADR-001) -------------------------------------
# Reddit OAuth2 application-only is FREE for read-only public data (no per-read
# price, unlike X pay-per-use) — so there is NO monthly read budget here, only
# rate-limit-aware backoff. Free OAuth allows ~100 QPM; we poll at a calm cadence
# and respect 429 / `x-ratelimit-*`. Reddit REQUIRES a unique `User-Agent`.

# Recommended Reddit collect cadence (seconds) — informational anchor for the
# scheduler (Reddit is cheaper than X but we still don't spam: every 5 minutes).
REDDIT_COLLECT_INTERVAL_SECONDS: Final = 5 * 60  # 300

# Hard per-ref cap on submissions read from ONE subreddit per tick (the
# `/r/{sub}/new` listing supports up to 100; 50 is plenty for a recent window).
REDDIT_MAX_RESULTS_PER_TICK: Final = 50

# Max 429 wait the reader sleeps INLINE before skipping the ref (seconds). Above
# this the ref is skipped this tick (retried next), mirroring the Twitter 429 cap.
REDDIT_RATE_LIMIT_INLINE_CAP_SECONDS: Final = 60

# OAuth2 token endpoint path (on the auth host, e.g. https://www.reddit.com), and
# how early (seconds) we refresh the access token before its `expires_in` elapses.
REDDIT_OAUTH_TOKEN_PATH: Final = "/api/v1/access_token"
REDDIT_TOKEN_EXPIRY_LEEWAY_SECONDS: Final = 60

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
# Hard time-limit grace over the soft limit for collect_tick (seconds). The
# soft limit equals `collect_lock_ttl_seconds` (a tick may use its whole lock
# window; SoftTimeLimitExceeded = valid partial run, buffered posts kept); the
# hard limit fires this much later and recycles the worker process if even the
# soft-limit cleanup wedges — a hung read can never hold a celery slot forever.
COLLECT_TICK_HARD_LIMIT_GRACE_SECONDS: Final = 30
