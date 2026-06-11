"""Application settings, sourced from environment / env files (pydantic-settings).

No magic literals: connection URLs and credentials come from the environment,
materialized by `make ansible-unpack` into `development/env/*.env`.
"""

import base64
from functools import lru_cache

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Hosts that are allowed to use plain http:// for public_base_url — dev G2 runs
# use http://localhost:8000; prod MUST use https:// (enforced by validator below).
_HTTP_ALLOWED_HOSTS = ("localhost", "127.0.0.1")

# SQLAlchemy 2.0 + psycopg3 driver scheme; the only place the dialect is named.
# `psycopg` (v3) serves both the sync engine (storage/) and the async engine the
# fastapi-users SQLAlchemy adapter needs (api/auth/) — same driver, no asyncpg.
_POSTGRES_DRIVER = "postgresql+psycopg"
_DEFAULT_POSTGRES_PORT = 5432

# Non-secret default for the access-token TTL (seconds) — a named constant, not a
# magic literal at the call site (CONVENTIONS). Overridable via JWT_LIFETIME_SECONDS.
_DEFAULT_JWT_LIFETIME_SECONDS = 3600

# Celery Beat cadence + per-user batch lock TTL (seconds) — named, non-secret
# defaults sourced from overview §4/§5 and ADR-002, overridable via env. Beat
# enqueues active-user batches once a minute and the scorer tick every 5 minutes;
# the batch lock TTL bounds a crashed worker's lock so it cannot deadlock forever
# (must exceed a typical batch but stay finite). Time is in SECONDS (CONVENTIONS).
_DEFAULT_BATCH_INTERVAL_SECONDS = 60
_DEFAULT_SCORER_INTERVAL_SECONDS = 300
_DEFAULT_BATCH_LOCK_TTL_SECONDS = 600

# Pipeline thresholds + embedding model (task-007). Named, non-secret defaults —
# never magic literals at the call site (CONVENTIONS). The embedding model is the
# single source for its name (its vector dim MUST equal storage `EMBEDDING_DIM`,
# arch §7 "pgvector dimension drift"); `all-MiniLM-L6-v2` → 384 dims. The dedup
# threshold is the estimated-Jaccard cutoff above which two texts collapse to one
# (MinHash), and the cluster threshold is the cosine-similarity cutoff for grouping.
_DEFAULT_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_DEFAULT_DEDUP_SIMILARITY_THRESHOLD = 0.8
_DEFAULT_CLUSTER_COSINE_THRESHOLD = 0.75

# Scorer (task-008). Named, non-secret defaults — never magic literals (CONVENTIONS).
# A cluster is "fresh"/scoreable if updated within this window (seconds); the scorer
# tick (every `scorer_interval_seconds`) only scores clusters inside it. The alert
# threshold is ALWAYS the user's per-topic watchlist `threshold` (NOT-NULL), so no
# global default threshold is needed.
_DEFAULT_SCORER_RECENT_WINDOW_SECONDS = 3600

# Alert delivery (task-009). Named, non-secret defaults — never magic literals.
# The Telegram Bot API base; `<token>` is appended per-request and NEVER logged.
# HTTP timeout bounds a hung Telegram/webhook call (seconds). The retry policy:
# `dispatch_alert` retries TRANSIENT failures up to `alert_max_retries` times with
# exponential backoff starting at `alert_retry_backoff_seconds`, capped at
# `alert_retry_backoff_max_seconds`, after which the alert is marked `failed`.
_DEFAULT_TELEGRAM_API_BASE_URL = "https://api.telegram.org"
# Billing — NOWPayments (task-010, ADR-004). The API base is the single source for
# the URL (non-secret, not a magic literal at the call site). The API key + IPN
# secret are secrets from sensitive.env; they DEFAULT to empty so the app boots
# without billing configured — billing endpoints error cleanly (503) when unset,
# rather than failing at startup (billing is optional). Secrets are NEVER logged.
_DEFAULT_NOWPAYMENTS_BASE_URL = "https://api.nowpayments.io/v1"

# Compliance & ops (task-011, overview §7 / ADR-002 §4). Named, non-secret
# defaults — never magic literals (CONVENTIONS); time is in SECONDS.
# Raw post `text` must not persist beyond this retention window; the hourly purge
# sweep NULLs `posts.text` for rows whose ingestion age (`fetched_at`) exceeds it.
# 48h = 172800s. The purge runs once an hour via Celery Beat.
_DEFAULT_RAW_CONTENT_RETENTION_SECONDS = 48 * 3600
_DEFAULT_RETENTION_PURGE_INTERVAL_SECONDS = 3600
# API rate-limit (slowapi, Redis-backed). The default per-key (authenticated
# user_id, else client IP) request budget per minute — generous + configurable so
# it does not throttle normal use, but caps abuse (overview §7). Named, settable.
_DEFAULT_RATE_LIMIT_PER_MINUTE = 120
# Bound the readiness probe's dependency checks so `/ready` cannot itself hang on a
# slow DB/Redis (edge case): a short, finite timeout in seconds.
_DEFAULT_READINESS_CHECK_TIMEOUT_SECONDS = 2

_DEFAULT_ALERT_HTTP_TIMEOUT_SECONDS = 10
_DEFAULT_ALERT_MAX_RETRIES = 5
_DEFAULT_ALERT_RETRY_BACKOFF_SECONDS = 2
_DEFAULT_ALERT_RETRY_BACKOFF_MAX_SECONDS = 600

# Observability — Sentry error-tracking (TASK-024). Named, non-secret defaults;
# `sentry_dsn` is intentionally empty → Sentry is OFF by default (dev safety).
# The DSN is a secret and lives in sensitive.env / vault; it is NEVER logged.
# `traces_sample_rate` controls the performance-monitoring sample fraction (0.0
# = off, 1.0 = 100%). `environment` and `release` tag every Sentry event so
# issues can be filtered by deploy stage and version.
_DEFAULT_SENTRY_TRACES_SAMPLE_RATE = 0.0
_DEFAULT_ENVIRONMENT = "dev"
_DEFAULT_RELEASE = "dev"

# Reliability — pending-sweep + Celery /ready (task-023). Named, non-secret
# defaults; time is in SECONDS (CONVENTIONS). The grace window prevents the sweep
# from racing in-flight dispatches (fresh pending < grace are never touched).
# max_batch caps the re-enqueue burst so a long broker outage doesn't flood the
# queue all at once. celery_ping_timeout bounds the control-bus inspect().ping()
# so /ready never hangs on a slow control channel.
_DEFAULT_PENDING_RESWEEP_GRACE_SECONDS = 300
_DEFAULT_PENDING_RESWEEP_INTERVAL_SECONDS = 300
_DEFAULT_PENDING_RESWEEP_MAX_BATCH = 500
_DEFAULT_CELERY_PING_TIMEOUT_SECONDS = 2

# Auth deeplink base URL (TASK-026). Named, non-secret default — never a magic
# literal at the call site (CONVENTIONS). Dev default → nginx on :80 (same-host
# compose stack); overridden in prod to the HTTPS domain via deploy.env /
# FRONTEND_BASE_URL env var.  The value is used by UserManager hooks to build
# verify/reset deeplinks that point at the frontend pages.
_DEFAULT_FRONTEND_BASE_URL = "http://localhost"

# Renewal notifications (TASK-027). Named, non-secret default — once per day.
# The beat task `check_expiring_subscriptions` runs at this interval (seconds).
# Daily cadence is sufficient because reminder windows are in whole days (7/3/1).
_DEFAULT_RENEWAL_CHECK_INTERVAL_SECONDS: int = 86_400

# Trending / showcase tenant (TASK-039). Named, non-secret defaults.
# `showcase_user_email`: system user created by ensure_showcase_tenant(); never
# a real login — hashed_password is random and unpublished (security invariant).
# `trending_top_k_default`: default number of clusters returned by GET /trending.
# `trending_top_k_max`: hard cap (422 if exceeded).
# `trending_window_seconds`: look-back window for showcase clusters (24h = 86400s).
_DEFAULT_SHOWCASE_USER_EMAIL = "showcase@internal"
_DEFAULT_TRENDING_TOP_K_DEFAULT = 10
_DEFAULT_TRENDING_TOP_K_MAX = 20
_DEFAULT_TRENDING_WINDOW_SECONDS: int = 86_400  # 24 hours

# Historical engagement baseline (TASK-041). Named, non-secret defaults; time in SECONDS.
# `engagement_baseline_window_seconds`: look-back window for per-channel history used to
# compute channel_avg in `_build_score_inputs`. Default 7 days = 604800 s.
# `engagement_baseline_min_posts`: minimum number of posts inside the window for a
# channel to use historical avg; fewer posts → fallback to batch-avg + log_event.
_DEFAULT_ENGAGEMENT_BASELINE_WINDOW_SECONDS: int = 604_800  # 7 days
_DEFAULT_ENGAGEMENT_BASELINE_MIN_POSTS: int = 10

# Free-plan alert delay (TASK-040). Named, non-secret default; time in SECONDS.
# Alerts created for Free-plan users are held back for this many seconds before
# delivery (deliver_after = now + delay). Pro/Team → no delay (deliver_after NULL).
# Default 1800 = 30 min. Override via env FREE_ALERT_DELAY_SECONDS (e.g. 60 for dev).
_DEFAULT_FREE_ALERT_DELAY_SECONDS: int = 1800

# Alert feedback — HMAC tokens + precision window (TASK-042). Named, non-secret
# defaults; time is in SECONDS (CONVENTIONS).
# `feedback_token_ttl_seconds`: how long a 👍/👎 URL button token remains valid
# (default 7d = 604800s). Matches the precision window so a rated alert is always
# within the precision window when the user clicks immediately.
# `precision_window_seconds`: sliding window for per-user alert precision metric
# (up/down counts, precision=up/(up+down), rated share). Default 7d = 604800s.
# Kept as a separate setting because the window may diverge from token TTL in
# future (e.g. a 30d precision window with 7d token lifetime).
# `public_base_url`: base URL of the publicly reachable deployment (e.g.
# https://foresignal.biz). Empty string = disabled (no 👍/👎 buttons); graceful
# degradation — alerts are still delivered, just without the feedback buttons.
# Must be set in deploy.env / Ansible group_vars for prod.
# `feedback_rate_limit_per_minute`: per-IP rate limit for the feedback endpoint.
# Lower than the authenticated API default — the endpoint is unauthenticated and
# should not be a vector for abuse. Named constant, not a magic literal.
_DEFAULT_FEEDBACK_TOKEN_TTL_SECONDS: int = 604_800  # 7 days
_DEFAULT_PRECISION_WINDOW_SECONDS: int = 604_800  # 7 days
_DEFAULT_PUBLIC_BASE_URL: str = ""
_DEFAULT_FEEDBACK_RATE_LIMIT_PER_MINUTE: int = 30

# Adaptive threshold + anti-fatigue guards (TASK-043). Named, non-secret defaults;
# time in SECONDS (CONVENTIONS).
# `threshold_adapt_interval_seconds`: how often the adapt-thresholds beat task runs (6h).
# `threshold_adapt_step`: how much threshold changes per tick (5.0 score units).
# `threshold_adapt_range`: max drift from floor in either direction (20.0 score units);
#   effective ceiling = floor + range; adaptation is clamped to [floor, floor+range].
# `threshold_adapt_min_ratings`: minimum feedback ratings in the 7d window required
#   before adaptation fires; fewer ratings → no-op (prevents noise from cold users).
# `threshold_adapt_up_share`: downvote share strictly above this → threshold grows.
# `threshold_adapt_down_share`: downvote share strictly below this → threshold shrinks.
# `alerts_per_hour_limit`: max NEW alert rows creatable per user per sliding 1h window.
#   Applied in the scorer create-path (not dispatch) — cheap guard before DB insert.
# `alert_group_window_seconds`: suppress duplicate (user, topic) alerts within this
#   window (default 1800 = 30 min). MVP: not vector-similarity — topic string match.
_DEFAULT_THRESHOLD_ADAPT_INTERVAL_SECONDS: int = 21_600  # 6 hours
_DEFAULT_THRESHOLD_ADAPT_STEP: float = 5.0
_DEFAULT_THRESHOLD_ADAPT_RANGE: float = 20.0
_DEFAULT_THRESHOLD_ADAPT_MIN_RATINGS: int = 5
_DEFAULT_THRESHOLD_ADAPT_UP_SHARE: float = 0.5
_DEFAULT_THRESHOLD_ADAPT_DOWN_SHARE: float = 0.2
_DEFAULT_ALERTS_PER_HOUR_LIMIT: int = 6
_DEFAULT_ALERT_GROUP_WINDOW_SECONDS: int = 1800  # 30 minutes

# Signal latency metric (TASK-036). Named, non-secret defaults; time in SECONDS.
# `latency_emit_interval_seconds`: how often the Beat task fires (default 5 min).
# `latency_window_seconds`: sliding window of delivered alerts to measure (default 1h).
_DEFAULT_LATENCY_EMIT_INTERVAL_SECONDS: int = 300
_DEFAULT_LATENCY_WINDOW_SECONDS: int = 3600

# Showcase autoposting (TASK-044). Named, non-secret defaults; time in SECONDS.
# `showcase_bot_token` / `showcase_channel_chat_id` are secrets (sensitive.env /
# vault); empty default → autoposting OFF (graceful degradation — deploy without
# a showcase channel is valid). NEVER logged or hardcoded.
# `showcase_post_interval_seconds`: how often the beat task fires (default 15 min).
# `showcase_post_delay_seconds`: minimum cluster age before posting (default 40 min =
#   2400s). INVARIANT: must be > free_alert_delay_seconds (value-ladder: channel is
#   slower than Free plan; validator enforces this at Settings construction).
# `showcase_post_min_score`: viral_score threshold for candidates (default 85.0).
# `showcase_posts_per_day_max`: anti-spam daily cap (default 8 posts/day UTC).
_DEFAULT_SHOWCASE_POST_INTERVAL_SECONDS: int = 900  # 15 minutes
_DEFAULT_SHOWCASE_POST_DELAY_SECONDS: int = 2400  # 40 minutes
_DEFAULT_SHOWCASE_POST_MIN_SCORE: float = 85.0
_DEFAULT_SHOWCASE_POSTS_PER_DAY_MAX: int = 8

# Proof-of-speed cases (TASK-045). Named, non-secret defaults.
# `showcase_case_min_score`: viral_score threshold for case fixation (default 90.0).
#   Intentionally higher than showcase_post_min_score (85.0) — only exceptional
#   signals become marketing proof-points.
# `cases_top_n_max`: hard cap for GET /cases (422 if exceeded); default 20.
_DEFAULT_SHOWCASE_CASE_MIN_SCORE: float = 90.0
_DEFAULT_CASES_TOP_N_MAX: int = 20

# Referral program (TASK-046). Named, non-secret default; amount in USDT.
# Fixed reward per referred user's first payment. Override via REFERRAL_REWARD_USDT.
_DEFAULT_REFERRAL_REWARD_USDT: float = 10.0

# Business-metrics daily aggregate (TASK-050). Named, non-secret default; time in SECONDS.
# `business_metrics_interval_seconds`: how often the Beat task fires (default 24h = 86400s).
# One run per day computes yesterday (complete) + today (partial running total).
# Override via env BUSINESS_METRICS_INTERVAL_SECONDS (e.g. 60 for dev/testing).
_DEFAULT_BUSINESS_METRICS_INTERVAL_SECONDS: int = 86_400  # 24 hours

# Lifecycle emails (TASK-069). Named, non-secret defaults; time in SECONDS/DAYS.
# `lifecycle_email_interval_seconds`: how often the Beat tick fires (default 24h).
#   Due-selection inside the tick is driven by per-user `*_last_sent_at` state,
#   so restarts / interval drift can never cause duplicates.
# `winback_inactive_days`: surrogate inactivity threshold — MAX(alerts.delivered_at)
#   older than this (or no alerts at all) with ≥1 watchlist → win-back candidate.
# `digest_top_k`: number of top-score delivered alerts in the weekly digest.
# `digest_period_days`: digest look-back window AND minimum days between digests.
# `unsubscribe_rate_limit_per_minute`: per-key budget for the unauthenticated
#   GET /email/unsubscribe endpoint (lower than the default auth'd API limit).
_DEFAULT_LIFECYCLE_EMAIL_INTERVAL_SECONDS: int = 86_400  # 24 hours
_DEFAULT_WINBACK_INACTIVE_DAYS: int = 14
_DEFAULT_DIGEST_TOP_K: int = 5
_DEFAULT_DIGEST_PERIOD_DAYS: int = 7
_DEFAULT_UNSUBSCRIBE_RATE_LIMIT_PER_MINUTE: int = 30

# CSRF/Origin allow-list (TASK-032). Named, non-secret default — the list of
# scheme+host values that are accepted as the `Origin` (or Referer fallback)
# header on cookie-auth mutations (POST/PUT/PATCH/DELETE).
# Dev default includes http://localhost (local compose SPA on :80/:3000) and
# http://localhost:3000 (Vite HMR dev server) so local development works
# without setting this env var. In production: override via ALLOWED_ORIGINS
# (comma-separated, e.g. "https://app.foresignal.biz,https://foresignal.biz").
_DEFAULT_ALLOWED_ORIGINS = "http://localhost,http://localhost:3000,http://localhost:4000"


# Field encryption key (TASK-032, Block C — at-rest encryption).
# A Fernet key: 32 random bytes, base64url-encoded (44 characters).
# In production: supply via FIELD_ENCRYPTION_KEY in sensitive.env / vault.
# Dev default: a deterministic valid Fernet key generated from a fixed seed
# (safe for dev — never in production). The validator enforces Fernet format.
# Key loss = data loss for encrypted columns (telegram_bot_token / webhook_url).
# Keep in secret manager and plan for rotation (re-encrypt with new key).
def _make_dev_fernet_key() -> str:
    """Generate a deterministic dev Fernet key from a fixed seed.

    This is a 32-byte key encoded as urlsafe-base64 (Fernet standard).
    NEVER used in production — the validator ensures the env var is set for
    non-localhost environments; this exists only so `uv run pytest -m 'not
    integration'` works without setting FIELD_ENCRYPTION_KEY.
    """
    # Fixed 32-byte seed for dev reproducibility (not a secret — dev only).
    seed = b"trendpulse-dev-field-enc-key-001"  # exactly 32 bytes
    return base64.urlsafe_b64encode(seed).decode("ascii")


_DEFAULT_FIELD_ENCRYPTION_KEY: str = _make_dev_fernet_key()

# TG account pool health + ops self-alert (TASK-035). Named, non-secret defaults.
# `pool_min_healthy` is the operational target: fewer healthy accounts = degraded
# (warn metric + self-alert). POOL_MIN=1 remains the hard floor in collector/constants
# so dev/tests with a single session still work.
# Code default is 3; prod sets POOL_MIN_HEALTHY=1 via deploy.env/Ansible while a
# single session is in use — raise when more sessions are added.
_DEFAULT_POOL_MIN_HEALTHY = 3
# Ops self-alert throttle: at most one Telegram message per reason per window.
_DEFAULT_OPS_ALERT_THROTTLE_SECONDS = 3600

# Email — templates service + SMTP transport (TASK-025). Named, non-secret
# defaults — never magic literals (CONVENTIONS). Dev defaults point to the
# local compose services (templates:3100, mailpit:1025). SMTP credentials are
# intentionally empty by default; mailpit does not require authentication.
# `smtp_from` is non-secret (a display name + address); set via deploy.env.
_DEFAULT_TEMPLATES_SERVICE_URL = "http://templates:3100"
_DEFAULT_SMTP_HOST = "mailpit"
_DEFAULT_SMTP_PORT = 1025
_DEFAULT_SMTP_FROM = "TrendPulse <noreply@trendpulse.local>"
_DEFAULT_EMAIL_RENDER_TIMEOUT_SECONDS = 10
# Bound the SMTP connect/send so a hung mail server can't block a Celery worker.
_DEFAULT_SMTP_TIMEOUT_SECONDS = 10


class Settings(BaseSettings):
    """Runtime configuration read from the process environment.

    `extra="ignore"` so that the shared `deploy.env`/`sensitive.env` files (which
    also carry compose-level keys) do not break instantiation. The DB connection
    is assembled from discrete `POSTGRES_*` parts so the **password lives only in
    `sensitive.env`** (CONVENTIONS: secrets never in code or committed env).
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Non-secret connection parts (defaults match the local compose service names).
    postgres_host: str = "postgres"
    postgres_port: int = _DEFAULT_POSTGRES_PORT
    postgres_db: str = "trendpulse"
    postgres_user: str = "trendpulse"
    # Secret — supplied at runtime via sensitive.env; no credential default in source.
    postgres_password: str = ""

    redis_url: str = "redis://redis:6379/0"

    # --- Celery scheduling + per-user batch lock (ADR-002). Non-secret, settable. ---
    batch_interval_seconds: int = _DEFAULT_BATCH_INTERVAL_SECONDS
    scorer_interval_seconds: int = _DEFAULT_SCORER_INTERVAL_SECONDS
    batch_lock_ttl_seconds: int = _DEFAULT_BATCH_LOCK_TTL_SECONDS

    # --- Pipeline (task-007). Non-secret, settable; defaults above. ---
    embedding_model_name: str = _DEFAULT_EMBEDDING_MODEL_NAME
    dedup_similarity_threshold: float = _DEFAULT_DEDUP_SIMILARITY_THRESHOLD
    cluster_cosine_threshold: float = _DEFAULT_CLUSTER_COSINE_THRESHOLD

    # --- Scorer (task-008). Non-secret, settable; defaults above. ---
    scorer_recent_window_seconds: int = _DEFAULT_SCORER_RECENT_WINDOW_SECONDS

    # --- Compliance & ops (task-011). Non-secret, settable; defaults above. ---
    raw_content_retention_seconds: int = _DEFAULT_RAW_CONTENT_RETENTION_SECONDS
    retention_purge_interval_seconds: int = _DEFAULT_RETENTION_PURGE_INTERVAL_SECONDS
    rate_limit_per_minute: int = _DEFAULT_RATE_LIMIT_PER_MINUTE
    readiness_check_timeout_seconds: int = _DEFAULT_READINESS_CHECK_TIMEOUT_SECONDS

    # --- Alert delivery (task-009). Non-secret, settable; defaults above. ---
    telegram_api_base_url: str = _DEFAULT_TELEGRAM_API_BASE_URL
    alert_http_timeout_seconds: int = _DEFAULT_ALERT_HTTP_TIMEOUT_SECONDS
    alert_max_retries: int = _DEFAULT_ALERT_MAX_RETRIES
    alert_retry_backoff_seconds: int = _DEFAULT_ALERT_RETRY_BACKOFF_SECONDS
    alert_retry_backoff_max_seconds: int = _DEFAULT_ALERT_RETRY_BACKOFF_MAX_SECONDS

    # --- Reliability — pending-sweep + Celery /ready (task-023). Non-secret,
    # settable; defaults above. ---
    # Grace window (seconds): pending alerts younger than this are in-flight and
    # must not be re-enqueued; only stale pending (older than grace) are swept.
    pending_resweep_grace_seconds: int = _DEFAULT_PENDING_RESWEEP_GRACE_SECONDS
    # Beat interval (seconds) for the resweep_pending_alerts task.
    pending_resweep_interval_seconds: int = _DEFAULT_PENDING_RESWEEP_INTERVAL_SECONDS
    # Max alerts re-enqueued per sweep tick (burst cap).
    pending_resweep_max_batch: int = _DEFAULT_PENDING_RESWEEP_MAX_BATCH
    # Timeout (seconds) for the Celery control-bus inspect().ping() in /ready.
    celery_ping_timeout_seconds: int = _DEFAULT_CELERY_PING_TIMEOUT_SECONDS

    # --- Billing — NOWPayments (task-010, ADR-004). Secrets from sensitive.env;
    # empty defaults so the app boots without billing configured (endpoints 503). ---
    nowpayments_api_key: str = ""
    nowpayments_ipn_secret: str = ""
    nowpayments_base_url: str = _DEFAULT_NOWPAYMENTS_BASE_URL

    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    # Comma-separated pool StringSession strings (technical accounts) from env
    # TELEGRAM_POOL_SESSIONS. Secret — supplied via sensitive.env; NEVER a user
    # session_string (overview §2/§7). Parsed via `telegram_pool_sessions()`.
    telegram_pool_sessions: str = ""

    # --- Auth secrets (fastapi-users + httpx-oauth, ADR-003). ---
    # NO defaults on the SECRET fields → a missing env var fails fast at startup
    # (AC6): pydantic raises a ValidationError when the value is absent. Source:
    # sensitive.env (ADR-005), never hardcoded. The env names are the UPPERCASE
    # field names (JWT_SECRET, OAUTH_STATE_SECRET, GOOGLE_CLIENT_ID/SECRET).
    jwt_secret: str
    oauth_state_secret: str
    google_client_id: str
    google_client_secret: str
    # Non-secret config — settable, with a named-constant default (not a magic literal).
    jwt_lifetime_seconds: int = _DEFAULT_JWT_LIFETIME_SECONDS
    # Auth cookie `Secure` flag: True in prod (HTTPS via nginx), but MUST be False
    # for local dev which serves over plain http on :80 (TLS is prod-only, task-001)
    # — a Secure cookie is never sent back over http, breaking login/session locally.
    auth_cookie_secure: bool = True
    # Swagger/Redoc/OpenAPI docs gating (TASK-019, security-relevant): docs are OFF by
    # default (prod) to avoid exposing the full API schema externally.  Dev enables via
    # env `SWAGGER_ENABLE=true`; prod must NOT set this flag.
    swagger_enable: bool = False

    # --- Auth deeplink (TASK-026). Non-secret; prod MUST set FRONTEND_BASE_URL to
    # the HTTPS domain (e.g. https://app.trendpulse.io) via deploy.env / ansible
    # group_vars. Dev default → same-host nginx on :80.  Value is used by
    # UserManager hooks to build verify/reset deeplinks for frontend pages. ---
    frontend_base_url: str = _DEFAULT_FRONTEND_BASE_URL

    # --- Renewal notifications (TASK-027). Non-secret, settable; default above.
    # Beat interval (seconds) for the check_expiring_subscriptions task. ---
    renewal_check_interval_seconds: int = _DEFAULT_RENEWAL_CHECK_INTERVAL_SECONDS

    # --- Trending / showcase tenant (TASK-039). Non-secret, settable; defaults above. ---
    # Email for the system showcase user (never a real login; password random).
    showcase_user_email: str = _DEFAULT_SHOWCASE_USER_EMAIL
    # Default and max number of trending items returned by GET /trending.
    trending_top_k_default: int = _DEFAULT_TRENDING_TOP_K_DEFAULT
    trending_top_k_max: int = _DEFAULT_TRENDING_TOP_K_MAX
    # Look-back window for showcase cluster scores (seconds). Default 24h.
    trending_window_seconds: int = _DEFAULT_TRENDING_WINDOW_SECONDS

    # --- Historical engagement baseline (TASK-041). Non-secret, settable; defaults above.
    # Look-back window (seconds) for per-channel history used to compute channel_avg.
    # Default 7d = 604800s. Override via env ENGAGEMENT_BASELINE_WINDOW_SECONDS.
    engagement_baseline_window_seconds: int = _DEFAULT_ENGAGEMENT_BASELINE_WINDOW_SECONDS
    # Minimum posts inside the window required to use historical avg; below this
    # threshold the scorer falls back to batch-avg behaviour + logs a baseline_fallback
    # event. Override via env ENGAGEMENT_BASELINE_MIN_POSTS.
    engagement_baseline_min_posts: int = _DEFAULT_ENGAGEMENT_BASELINE_MIN_POSTS

    # --- Free-plan alert delay (TASK-040). Non-secret, settable; default above.
    # Seconds to delay alert delivery for Free-plan users. Override in dev with 60. ---
    free_alert_delay_seconds: int = _DEFAULT_FREE_ALERT_DELAY_SECONDS

    # --- Alert feedback 👍/👎 (TASK-042). Non-secret, settable; defaults above.
    # HMAC-signed token TTL (seconds) for feedback URL buttons. Default 7d.
    # Precision metric sliding window (seconds). Default 7d.
    # Public base URL for the deployment — empty = buttons disabled (graceful degradation).
    # Per-minute rate limit for the unauthenticated /feedback/{token} endpoint. ---
    feedback_token_ttl_seconds: int = _DEFAULT_FEEDBACK_TOKEN_TTL_SECONDS
    precision_window_seconds: int = _DEFAULT_PRECISION_WINDOW_SECONDS
    public_base_url: str = _DEFAULT_PUBLIC_BASE_URL
    feedback_rate_limit_per_minute: int = _DEFAULT_FEEDBACK_RATE_LIMIT_PER_MINUTE

    # --- Adaptive threshold + anti-fatigue guards (TASK-043). Non-secret, settable;
    # defaults above. ---
    # Beat interval (seconds) for the adapt-thresholds task (default 6h).
    threshold_adapt_interval_seconds: int = _DEFAULT_THRESHOLD_ADAPT_INTERVAL_SECONDS
    # Score-unit step per adapt tick (how much threshold shifts).
    threshold_adapt_step: float = _DEFAULT_THRESHOLD_ADAPT_STEP
    # Maximum drift from floor; ceiling = floor + range (score units).
    threshold_adapt_range: float = _DEFAULT_THRESHOLD_ADAPT_RANGE
    # Minimum ratings in the 7d window before adaptation fires.
    threshold_adapt_min_ratings: int = _DEFAULT_THRESHOLD_ADAPT_MIN_RATINGS
    # Downvote share strictly above this → threshold grows (e.g. 0.5 = 50%).
    threshold_adapt_up_share: float = _DEFAULT_THRESHOLD_ADAPT_UP_SHARE
    # Downvote share strictly below this → threshold shrinks (e.g. 0.2 = 20%).
    threshold_adapt_down_share: float = _DEFAULT_THRESHOLD_ADAPT_DOWN_SHARE
    # Max new alert rows creatable per user per sliding 1h window (anti-fatigue).
    # INVARIANT: the rate-guard window counts alerts.first_seen (== cluster first_seen),
    # which only covers creations from clusters inside scorer_recent_window_seconds —
    # keep scorer_recent_window_seconds <= 1h (the guard window) or older clusters'
    # alerts silently escape this cap.
    alerts_per_hour_limit: int = _DEFAULT_ALERTS_PER_HOUR_LIMIT
    # Suppress duplicate (user, topic) alerts within this window (seconds).
    alert_group_window_seconds: int = _DEFAULT_ALERT_GROUP_WINDOW_SECONDS

    # --- Signal latency metric (TASK-036). Non-secret, settable; defaults above.
    # Beat interval (seconds) for the emit_signal_latency_task.
    # Sliding window (seconds) of delivered alerts included in the metric. ---
    latency_emit_interval_seconds: int = _DEFAULT_LATENCY_EMIT_INTERVAL_SECONDS
    latency_window_seconds: int = _DEFAULT_LATENCY_WINDOW_SECONDS

    # --- Email — templates service + SMTP transport (TASK-025). ---
    # Templates service URL — non-secret, from deploy.env; dev → compose service.
    templates_service_url: str = _DEFAULT_TEMPLATES_SERVICE_URL
    # SMTP parameters — host/port/from are non-secret (deploy.env); credentials
    # are secrets (sensitive.env, default empty → mailpit dev mode / no auth).
    smtp_host: str = _DEFAULT_SMTP_HOST
    smtp_port: int = _DEFAULT_SMTP_PORT
    # Credentials — empty default; mailpit does not require authentication.
    # In production, set SMTP_USER / SMTP_PASSWORD via sensitive.env / vault.
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = _DEFAULT_SMTP_FROM
    smtp_starttls: bool = False
    # Render timeout (seconds) for HTTP calls to the templates service.
    email_render_timeout_seconds: int = _DEFAULT_EMAIL_RENDER_TIMEOUT_SECONDS
    # SMTP connect/send timeout (seconds) — bounds a hung mail server.
    smtp_timeout_seconds: int = _DEFAULT_SMTP_TIMEOUT_SECONDS

    # --- TG pool health + ops self-alert (TASK-035). ---
    # Operational pool target: fewer healthy accounts than this = degraded (warn +
    # self-alert). Non-secret; prod sets POOL_MIN_HEALTHY=1 via Ansible deploy.env
    # while only one session is provisioned (raise to 3 once pool is expanded).
    pool_min_healthy: int = _DEFAULT_POOL_MIN_HEALTHY
    # Secrets — ops bot token + chat id; empty default → self-alert off (metric only).
    # Supplied via sensitive.env / vault; NEVER logged or hardcoded.
    ops_telegram_bot_token: str = ""
    ops_telegram_chat_id: str = ""
    # Non-secret: throttle window (seconds) per alert reason (default 1 hour).
    ops_alert_throttle_seconds: int = _DEFAULT_OPS_ALERT_THROTTLE_SECONDS

    # --- Showcase autoposting (TASK-044). ---
    # Secrets — showcase bot token + channel chat id; empty default → autoposting
    # OFF (graceful degradation). Supplied via sensitive.env / vault; NEVER logged.
    # In MVP: may reuse the same bot as ops (same token, different chat), but the
    # config keys are intentionally separate (zones of responsibility).
    showcase_bot_token: str = ""  # secret
    showcase_channel_chat_id: str = ""
    # Non-secret: beat interval (seconds) for the showcase-autopost task.
    showcase_post_interval_seconds: int = _DEFAULT_SHOWCASE_POST_INTERVAL_SECONDS
    # Non-secret: minimum cluster age (seconds) before autoposting. INVARIANT:
    # must be > free_alert_delay_seconds (enforced by validator below).
    showcase_post_delay_seconds: int = _DEFAULT_SHOWCASE_POST_DELAY_SECONDS
    # Non-secret: viral_score threshold for candidates.
    showcase_post_min_score: float = _DEFAULT_SHOWCASE_POST_MIN_SCORE
    # Non-secret: anti-spam daily cap (UTC day).
    showcase_posts_per_day_max: int = _DEFAULT_SHOWCASE_POSTS_PER_DAY_MAX

    # --- Proof-of-speed cases (TASK-045). Non-secret, settable; defaults above. ---
    # Minimum viral_score for a cluster to be fixed as a marketing case.
    # Higher than showcase_post_min_score (85.0) — exceptional signals only.
    showcase_case_min_score: float = _DEFAULT_SHOWCASE_CASE_MIN_SCORE
    # Hard cap for GET /cases (422 if top_n exceeds this). Default 20.
    cases_top_n_max: int = _DEFAULT_CASES_TOP_N_MAX

    # --- Referral program (TASK-046). Non-secret, settable; default above. ---
    # Fixed USDT reward paid to the referrer when a referred user makes their first
    # payment. Override via env REFERRAL_REWARD_USDT (e.g. for A/B testing the amount).
    referral_reward_usdt: float = _DEFAULT_REFERRAL_REWARD_USDT

    # --- Business-metrics daily aggregate (TASK-050). Non-secret, settable; default above.
    # Beat interval (seconds) for the aggregate_business_metrics task. Default 24h. ---
    business_metrics_interval_seconds: int = _DEFAULT_BUSINESS_METRICS_INTERVAL_SECONDS

    # --- Lifecycle emails (TASK-069). Non-secret, settable; defaults above. ---
    # Beat interval (seconds) for the send_lifecycle_emails tick. Default 24h.
    lifecycle_email_interval_seconds: int = _DEFAULT_LIFECYCLE_EMAIL_INTERVAL_SECONDS
    # Inactivity surrogate threshold (days) before a win-back email is due.
    winback_inactive_days: int = _DEFAULT_WINBACK_INACTIVE_DAYS
    # Number of top-score delivered alerts included in the weekly digest.
    digest_top_k: int = _DEFAULT_DIGEST_TOP_K
    # Digest look-back window and minimum days between digests.
    digest_period_days: int = _DEFAULT_DIGEST_PERIOD_DAYS
    # Per-minute rate limit for the unauthenticated GET /email/unsubscribe endpoint.
    unsubscribe_rate_limit_per_minute: int = _DEFAULT_UNSUBSCRIBE_RATE_LIMIT_PER_MINUTE

    # --- CSRF/Origin allow-list (TASK-032). Non-secret, settable; default above.
    # Comma-separated scheme+host values accepted in the Origin (or Referer fallback)
    # header for cookie-auth mutations. Override via env ALLOWED_ORIGINS in prod. ---
    allowed_origins: str = _DEFAULT_ALLOWED_ORIGINS

    # --- Field encryption key (TASK-032 Block C, at-rest encryption). Secret.
    # Fernet key (32-byte urlsafe-base64, 44 chars). Supplied via sensitive.env /
    # vault (FIELD_ENCRYPTION_KEY). Dev default: deterministic placeholder (above).
    # WARNING: loss of this key = permanent loss of telegram_bot_token / webhook_url.
    # Store in secret-manager; document rotation plan (re-encrypt with new key). ---
    field_encryption_key: str = _DEFAULT_FIELD_ENCRYPTION_KEY

    # --- Observability — Sentry (TASK-024). DSN is a secret (sensitive.env); empty
    # default → Sentry off. Non-secret settings have named-constant defaults above.---
    # Secret — supplied via sensitive.env / vault; NEVER logged or hardcoded.
    sentry_dsn: str = ""
    # Non-secret, settable: performance-tracing sample rate (0.0 = tracing off).
    sentry_traces_sample_rate: float = _DEFAULT_SENTRY_TRACES_SAMPLE_RATE
    # Non-secret: deployment stage tag (dev/staging/prod).
    environment: str = _DEFAULT_ENVIRONMENT
    # Non-secret: release tag (git sha / image tag injected at build time).
    release: str = _DEFAULT_RELEASE

    @field_validator("showcase_post_delay_seconds")
    @classmethod
    def validate_showcase_delay_invariant(cls, v: int, info: ValidationInfo) -> int:
        """Enforce: showcase_post_delay_seconds > free_alert_delay_seconds.

        The public showcase channel must be SLOWER than the Free-plan alert delay —
        otherwise the channel gives away signals faster than the paid tier, breaking
        the value ladder (Discussion TASK-044 / Invariants).

        Uses ValidationInfo.data (pydantic-settings v2): `free_alert_delay_seconds`
        must be declared BEFORE `showcase_post_delay_seconds` in the class body for
        `info.data` to contain its value at validation time.
        """
        free_delay = info.data.get("free_alert_delay_seconds")
        if not isinstance(free_delay, int):
            # free_alert_delay_seconds must appear before this field in the class body.
            # If it is missing from info.data it means field ordering is wrong or the
            # value failed its own validation — hard error so the misconfiguration is
            # visible immediately rather than silently skipping the invariant check.
            raise ValueError(
                "Cannot validate showcase_post_delay_seconds: "
                "free_alert_delay_seconds is absent from validation context. "
                "Ensure free_alert_delay_seconds is declared before "
                "showcase_post_delay_seconds in the Settings class body."
            )
        if v <= free_delay:
            raise ValueError(
                f"showcase_post_delay_seconds ({v}s) must be strictly greater than "
                f"free_alert_delay_seconds ({free_delay}s). "
                "The showcase channel must be slower than the Free plan (value ladder)."
            )
        return v

    @field_validator("threshold_adapt_step", "threshold_adapt_range")
    @classmethod
    def validate_adapt_positive(cls, v: float) -> float:
        """Fail fast on misconfig: step/range must be positive (ceiling >= floor)."""
        if v <= 0:
            raise ValueError("threshold_adapt_step/range must be > 0")
        return v

    @field_validator("threshold_adapt_down_share")
    @classmethod
    def validate_adapt_shares(cls, v: float, info: ValidationInfo) -> float:
        """Fail fast on misconfig: 0 <= down_share < up_share <= 1 (dead zone sane)."""
        up = info.data.get("threshold_adapt_up_share")
        if not 0.0 <= v <= 1.0 or (isinstance(up, float) and not v < up <= 1.0):
            raise ValueError(
                "adapt shares must satisfy 0 <= threshold_adapt_down_share < "
                "threshold_adapt_up_share <= 1"
            )
        return v

    @field_validator("public_base_url", mode="before")
    @classmethod
    def validate_public_base_url(cls, v: object) -> object:
        """Validate public_base_url: empty (feature off) or secure URL.

        Rules:
        - Empty string: allowed — feedback buttons are disabled (graceful degradation).
        - http:// scheme: allowed ONLY for localhost / 127.0.0.1 (dev G2 runs).
          Other http:// URLs are rejected to prevent accidental non-TLS prod deploys.
        - https:// scheme: always allowed.
        - Any other scheme or format: rejected.
        """
        url = str(v).strip() if v is not None else ""
        if not url:
            return url
        if url.startswith("https://"):
            return url
        if url.startswith("http://"):
            # Allow plain http only for localhost / 127.0.0.1 (dev G2 use-cases).
            # Extract the host part (between "http://" and the next "/" or end).
            rest = url[len("http://") :]
            host = rest.split("/")[0].split(":")[0]  # strip port if present
            if host in _HTTP_ALLOWED_HOSTS:
                return url
            raise ValueError(
                f"public_base_url must use https:// in non-local environments "
                f"(got http:// with host '{host}'). "
                f"Allowed http:// hosts: {_HTTP_ALLOWED_HOSTS}."
            )
        raise ValueError(
            f"public_base_url must be empty, start with 'https://', or start with "
            f"'http://' for localhost/127.0.0.1 (got: {url!r})."
        )

    @field_validator("field_encryption_key")
    @classmethod
    def validate_fernet_key(cls, v: str) -> str:
        """Fail fast if field_encryption_key is not a valid Fernet key.

        A Fernet key must be exactly 32 bytes when base64url-decoded (44 chars
        with padding). We validate at startup so a misconfigured key is caught
        immediately, not at first encrypt/decrypt.
        """
        try:
            decoded = base64.urlsafe_b64decode(v.encode("ascii") + b"==")
        except Exception as exc:
            raise ValueError(
                "FIELD_ENCRYPTION_KEY must be a valid base64url-encoded string (Fernet key format)."
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                f"FIELD_ENCRYPTION_KEY must decode to exactly 32 bytes "
                f"(got {len(decoded)} bytes). "
                'Generate with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        return v

    @property
    def allowed_origins_set(self) -> frozenset[str]:
        """Parse the comma-separated allowed_origins string into a frozenset.

        Strips whitespace from each entry; ignores empty entries. Used by
        CSRFOriginMiddleware at startup (constructed once, not per-request).
        """
        return frozenset(o.strip() for o in self.allowed_origins.split(",") if o.strip())

    @property
    def database_url(self) -> str:
        """SQLAlchemy DSN assembled from parts (password sourced from env)."""
        return (
            f"{_POSTGRES_DRIVER}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


def telegram_pool_sessions(settings: Settings) -> list[str]:
    """Parse `telegram_pool_sessions` (comma-separated) into a list of sessions.

    Empty entries are stripped. Returns `[]` when unset. Secrets are never logged.
    """
    return [s.strip() for s in settings.telegram_pool_sessions.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance."""
    return Settings()
