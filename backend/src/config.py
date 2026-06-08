"""Application settings, sourced from environment / env files (pydantic-settings).

No magic literals: connection URLs and credentials come from the environment,
materialized by `make ansible-unpack` into `development/env/*.env`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

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
_DEFAULT_ALERT_HTTP_TIMEOUT_SECONDS = 10
_DEFAULT_ALERT_MAX_RETRIES = 5
_DEFAULT_ALERT_RETRY_BACKOFF_SECONDS = 2
_DEFAULT_ALERT_RETRY_BACKOFF_MAX_SECONDS = 600


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

    # --- Alert delivery (task-009). Non-secret, settable; defaults above. ---
    telegram_api_base_url: str = _DEFAULT_TELEGRAM_API_BASE_URL
    alert_http_timeout_seconds: int = _DEFAULT_ALERT_HTTP_TIMEOUT_SECONDS
    alert_max_retries: int = _DEFAULT_ALERT_MAX_RETRIES
    alert_retry_backoff_seconds: int = _DEFAULT_ALERT_RETRY_BACKOFF_SECONDS
    alert_retry_backoff_max_seconds: int = _DEFAULT_ALERT_RETRY_BACKOFF_MAX_SECONDS

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
