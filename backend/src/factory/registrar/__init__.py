"""Telegram registrars for the account factory (TASK-133, Layer B2).

`base` defines the `TelegramRegistrar` Protocol + `RegisteredSession` DTO; `fake` is
the deterministic CI impl; `telethon` is the real Telethon-backed registrar (lazy
import, config-gated, never exercised in CI).
"""
