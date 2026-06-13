"""Offline backfill: download crypto-RU channel history WITH text to local SQLite.

WHY a separate script (not the prod collector): prod TTLs `posts.text` ≤48h and only
embeds a fraction — useless for re-clustering history. For an honest scoring eval we
need raw text retained so we can embed → cluster → score offline and judge whether the
viral_score actually ranks real cross-channel stories. This writes to a LOCAL sqlite
file only; it imports nothing from prod and mutates no prod state.

AUTH (required — Telethon needs an authorized account even for public channels):
  Provide via eval_offline/.env or environment:
    TG_API_ID=...            # https://my.telegram.org → API development tools
    TG_API_HASH=...
    TG_SESSION=...           # a StringSession for a DEDICATED account (recommended),
                             # or leave empty to do an interactive phone login once,
                             # which prints a reusable StringSession.
  Do NOT reuse the prod pool session: a second IP on the same session competes with
  the live collector for the FLOOD_WAIT budget and can invalidate it.

RATE LIMITS (pool = effectively 1 account): channels are read sequentially with a
sleep between them; FloodWaitError is slept (short) or the channel is deferred (long).
Resumable: re-running skips (channel, msg_id) already stored, and resumes each channel
from its oldest stored message going further back until the cutoff.

USAGE:
  cd eval_offline
  uv run --with telethon python backfill_telegram.py --months 9
  uv run --with telethon python backfill_telegram.py --months 9 --only @forklog,@incrypted
  uv run --with telethon python backfill_telegram.py --login   # one-time, prints session
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from channels_crypto_ru import HANDLES

DB_PATH = Path(__file__).parent / "data" / "corpus.sqlite"
INTER_CHANNEL_SLEEP_S = 8.0          # gentle on the pool between channels
FLOOD_INLINE_CAP_S = 300             # sleep floods ≤5min inline; defer longer ones
PROGRESS_EVERY = 500


def _load_env() -> None:
    """Load eval_offline/.env (KEY=VALUE lines) into os.environ if present."""
    env = Path(__file__).parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            handle      TEXT NOT NULL,
            msg_id      INTEGER NOT NULL,
            posted_at   TEXT NOT NULL,      -- ISO8601 UTC
            text        TEXT,
            views       INTEGER NOT NULL DEFAULT 0,
            forwards    INTEGER NOT NULL DEFAULT 0,
            reactions   INTEGER NOT NULL DEFAULT 0,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (handle, msg_id)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS ix_posts_posted ON posts(posted_at)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_posts_handle ON posts(handle)")
    con.commit()
    return con


def _oldest_stored(con: sqlite3.Connection, handle: str) -> int | None:
    """Min msg_id stored for handle (to resume going further back), or None."""
    row = con.execute("SELECT min(msg_id) FROM posts WHERE handle=?", (handle,)).fetchone()
    return row[0] if row and row[0] is not None else None


def _reaction_count(msg) -> int:
    r = getattr(msg, "reactions", None)
    if not r or not getattr(r, "results", None):
        return 0
    return sum(int(getattr(x, "count", 0)) for x in r.results)


async def _backfill_channel(
    client: TelegramClient, con: sqlite3.Connection, handle: str, cutoff: datetime
) -> tuple[int, str]:
    """Download `handle` newer than `cutoff`; return (new_rows, status)."""
    name = handle.lstrip("@")
    try:
        entity = await client.get_entity(name)
    except Exception as exc:  # noqa: BLE001 — log + skip, never crash the whole run
        return 0, f"resolve_failed:{type(exc).__name__}"

    now = datetime.now(timezone.utc).isoformat()
    max_id = _oldest_stored(con, handle) or 0  # resume below the oldest we have
    new = 0
    try:
        kwargs = {"reverse": False}
        if max_id:
            kwargs["max_id"] = max_id  # continue further back from oldest stored
        async for msg in client.iter_messages(entity, **kwargs):
            if msg.date and msg.date < cutoff:
                break  # reached the time horizon
            con.execute(
                "INSERT OR IGNORE INTO posts VALUES (?,?,?,?,?,?,?,?)",
                (
                    handle,
                    msg.id,
                    (msg.date or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
                    msg.message or None,
                    int(getattr(msg, "views", 0) or 0),
                    int(getattr(msg, "forwards", 0) or 0),
                    _reaction_count(msg),
                    now,
                ),
            )
            new += 1
            if new % PROGRESS_EVERY == 0:
                con.commit()
                print(f"    {handle}: +{new} …", flush=True)
    except FloodWaitError as exc:
        con.commit()
        if exc.seconds <= FLOOD_INLINE_CAP_S:
            print(f"    {handle}: FLOOD_WAIT {exc.seconds}s — sleeping", flush=True)
            await asyncio.sleep(exc.seconds)
            n2, _ = await _backfill_channel(client, con, handle, cutoff)
            return new + n2, "ok(after_flood)"
        return new, f"deferred_flood:{exc.seconds}s"
    con.commit()
    return new, "ok"


async def main_async(months: int, only: list[str] | None, login_only: bool) -> int:
    _load_env()
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        print("ERROR: set TG_API_ID and TG_API_HASH (eval_offline/.env or env).", file=sys.stderr)
        return 2

    session = StringSession(os.environ.get("TG_SESSION", "") or None)
    client = TelegramClient(session, int(api_id), api_hash)
    await client.start()  # interactive phone login only if session is empty/invalid
    me = await client.get_me()
    print(f"authorized as: {getattr(me, 'username', None) or me.id}")
    if login_only:
        # ONLY here do we expose the session string (interactive local login flow).
        # Never printed during a normal backfill run — it is a secret.
        print(f"\nTG_SESSION={client.session.save()}\n")
        await client.disconnect()
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(months * 30.5))
    targets = only if only else HANDLES
    con = _db()
    print(f"backfill {len(targets)} channels, cutoff={cutoff.date()} ({months}mo)\n")
    grand = 0
    for i, handle in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {handle}", flush=True)
        n, status = await _backfill_channel(client, con, handle, cutoff)
        grand += n
        print(f"    -> +{n} rows ({status})", flush=True)
        await asyncio.sleep(INTER_CHANNEL_SLEEP_S)

    total = con.execute("SELECT count(*) FROM posts").fetchone()[0]
    chans = con.execute("SELECT count(DISTINCT handle) FROM posts").fetchone()[0]
    print(f"\nDONE +{grand} new. corpus: {total} posts across {chans} channels -> {DB_PATH}")
    await client.disconnect()
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--months", type=int, default=9, help="how far back to fetch")
    p.add_argument("--only", type=str, default="", help="comma-separated handles subset")
    p.add_argument("--login", action="store_true", help="just log in and print session string")
    a = p.parse_args()
    only = [h.strip() for h in a.only.split(",") if h.strip()] or None
    return asyncio.run(main_async(a.months, only, a.login))


if __name__ == "__main__":
    raise SystemExit(main())
