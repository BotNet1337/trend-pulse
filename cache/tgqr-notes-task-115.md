# TASK-115 notes — pool health snapshot Redis bridge (for TASK-116)

## Redis key
- Key: `pool:health:latest` (constant `POOL_HEALTH_REDIS_KEY` in `collector/constants.py`).
- Value: a single JSON object (string), written via `redis.set(key, json, ex=TTL)`.
- TTL: `POOL_HEALTH_SNAPSHOT_TTL_SECONDS = 300` (5 minutes). When the worker dies, the key
  expires after 300s and `GET` returns `None` → the API must treat absence as "no recent snapshot".

## Writer
- `observability.pool_health.emit_pool_health(pool, settings, redis)` writes the snapshot each
  collect-tick (called from `TelegramCollector._emit_health_best_effort`, once per `read()` cycle).
- Best-effort: a serialization/Redis failure is logged and swallowed; the key may therefore be
  stale or absent — the API must tolerate both.

## JSON schema (snapshot object)
```jsonc
{
  "size":        int,      // total accounts in the pool
  "cooling":     int,      // LIVE accounts in FLOOD_WAIT cooldown
  "quarantined": int,      // permanently dead/quarantined accounts
  "healthy":     int,      // size - cooling - quarantined
  "target":      int,      // settings.pool_min_healthy
  "degraded":    bool,     // healthy < target
  "as_of":       string,   // UTC ISO-8601 timestamp, e.g. "2026-06-16T10:11:12.345678+00:00"
                           //   (datetime.now(UTC).isoformat())
  "accounts": [            // one entry per pool account, in pool-INDEX order
    {
      "index":                      int,            // stable pool position — the ONLY per-account id
      "state":                      "healthy" | "cooling" | "quarantined",
      "cooldown_remaining_seconds": float | null,   // present (>0) ONLY when state == "cooling"; else null
      "last_error_reason":          string          // "" | "FLOOD_WAIT" | error class name
                                                    //   (e.g. "AuthKeyDuplicatedError"); last-known,
                                                    //   may persist after recovery
    }
  ]
}
```

### Secret invariant
No session strings, api_hash, or fingerprints appear anywhere in the snapshot. Per-account identity
is the integer `index` only. (Asserted by `test_emit_pool_health_snapshot_has_no_secrets`.)

## How TASK-116 should read + parse + compute staleness
1. `raw = redis.get("pool:health:latest")`.
   - `None` → no recent snapshot (worker down ≥ TTL, or never ran) → surface as `stale=true` /
     `unavailable` to the client. Do NOT 500.
2. `snapshot = json.loads(raw)`. Validate with a Pydantic model mirroring the schema above
   (system-boundary validation per CONVENTIONS); reject/treat-as-stale on parse/validation error.
3. Staleness: parse `as_of` (`datetime.fromisoformat`), compute
   `age = now(UTC) - as_of`. Mark `stale = age > <staleness_threshold>`. A sensible threshold is a
   small multiple of the collect cadence (e.g. ~2x the tick interval). Note the key's own TTL is
   300s, so any present snapshot is at most ~5min old; the API's own threshold can be tighter for a
   "fresh vs stale" badge.
4. Expose `size/healthy/cooling/quarantined/quarantined/target/degraded`, the per-account
   `accounts` list, `as_of`, and a derived `stale` flag.

## Touched files (TASK-115)
- `backend/src/collector/constants.py` — key + TTL constants
- `backend/src/collector/telegram/account_pool.py` — `last_error_reason`, `AccountStatus`,
  `account_statuses()`, `note_current_error()`
- `backend/src/collector/telegram/reader.py` — set reason at existing catch sites; pass redis
- `backend/src/observability/pool_health.py` — `accounts`+`as_of` in snapshot, Redis write
- tests: `test_account_pool_rotation.py`, `test_auth_quarantine.py`, `test_pool_health.py`
