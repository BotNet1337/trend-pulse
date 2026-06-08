"""Telegram source adapter (Telethon). Public surface re-exported here."""

from collector.telegram.account_pool import AccountPool
from collector.telegram.mapper import map_entity
from collector.telegram.reader import TelegramCollector

__all__ = ["AccountPool", "TelegramCollector", "map_entity"]
