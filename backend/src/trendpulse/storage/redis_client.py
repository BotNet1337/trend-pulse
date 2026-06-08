"""Thin typed Redis client factory (URL sourced from Settings)."""

from redis import Redis

from trendpulse.config import get_settings


def get_redis_client() -> Redis:
    """Return a Redis client built from `Settings.redis_url`."""
    return Redis.from_url(get_settings().redis_url)
