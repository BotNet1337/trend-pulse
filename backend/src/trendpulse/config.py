"""Application settings, sourced from environment / env files (pydantic-settings).

No magic literals: connection URLs and credentials come from the environment,
materialized by `make ansible-unpack` into `development/env/*.env`.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# SQLAlchemy 2.0 + psycopg3 driver scheme; the only place the dialect is named.
_POSTGRES_DRIVER = "postgresql+psycopg"
_DEFAULT_POSTGRES_PORT = 5432


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

    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None

    @property
    def database_url(self) -> str:
        """SQLAlchemy DSN assembled from parts (password sourced from env)."""
        return (
            f"{_POSTGRES_DRIVER}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached `Settings` instance."""
    return Settings()
