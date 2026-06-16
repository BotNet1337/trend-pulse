# TASK-118 notes — pool-health honesty (read-outcome + `failing` state)

Branch `feat/pool-health-revive`, baseline `98bd84c`. Part of EPIC-POOL-HEALTH-REVIVE.
This is the OBSERVABILITY foundation 119/120 build on.

## New `_Account` fields (annotation-only — never touch rotation/cooldown/quarantine)
`backend/src/collector/telegram/account_pool.py`
- `last_read_ok_at: float | None` — monotonic stamp of the last CLEAN read (None until first OK).
- `consecutive_read_failures: int` — read failures since last clean read (reset to 0 on success).
- `first_read_failure_at: float | None` — monotonic stamp of the FIRST failure since last success;
  starts the no-read window. Reset on success.

New helpers (mirror `note_current_error`, current-account only):
- `note_read_success()` — stamp `last_read_ok_at`, zero failures + window.
- `note_read_failure(reason)` — increment, stamp window start (first only), set `last_error_reason`
  (error CLASS NAME, never a secret).
- `_is_failing(account, now)` (static, pure) — used by `account_statuses()`.

`AccountState` Literal now: `"healthy" | "cooling" | "quarantined" | "failing"`.
Precedence in `account_statuses()`: quarantined > cooling > failing > healthy.
`failing` iff LIVE and (`consecutive_read_failures >= POOL_FAILING_THRESHOLD` OR
`last_read_ok_at is None and first_read_failure_at set and now-first >= NO_READ_WINDOW`).

## Constants (`collector/constants.py`)
- `POOL_FAILING_THRESHOLD = 5`
- `POOL_FAILING_NO_READ_WINDOW_SECONDS = 1800` (30 min)
- `INGEST_STALENESS_REDIS_KEY = "ingest:staleness:latest"`
- `INGEST_STALENESS_TTL_SECONDS = 900` (15 min)

## Reader wiring (`telegram/reader.py`)
- clean iteration → `report_success()` + `note_read_success()`.
- transient `auth_error` (entity-resolve) branch AND mid-iteration transient branch →
  `note_read_failure(type(exc).__name__)`. THIS is the formerly-silent "wrong session ID" gap.
- FLOOD_WAIT branch unchanged (cooling, NOT a read failure — never increments the counter).
- `_emit_health_best_effort(..., emit_metric: bool = True)`: once-per-tick `read()`-end call keeps
  the metric/snapshot write; notify-only sites pass `emit_metric=False` (cadence fix, ~1 emit/sec→1/tick).

## Snapshot shape (`pool:health:latest`, written by `observability/pool_health.py::_publish_snapshot`)
JSON: aggregates `{size, cooling, quarantined, healthy, target, degraded}` + `as_of` (UTC-ISO) +
`accounts: [{index, state, cooldown_remaining_seconds, last_error_reason}]` + **NEW**
`ingest_contradiction: bool`.
- `ingest_contradiction` = `size>0 and healthy==size` AND ingest-staleness bridge key says `stale`.
  Fail-open to false (missing/expired/malformed key, or RedisError). Index-only identity, no secrets.
- `healthy` aggregate is `size - cooling - quarantined` (a `failing` account is still counted in
  `healthy` — that's WHY the contradiction matters: all-green aggregate + stale ingest).

## Ingest-staleness bridge (cross-process, no DB on hot path)
- `signal_latency.publish_ingest_staleness(redis, {stale, age_s})` writes `INGEST_STALENESS_REDIS_KEY`
  with TTL. Called by `observability/tasks.py` after `emit_ingest_staleness` (beat process, Postgres).
- The collect-tick snapshot READS that key — never queries Postgres itself.

## API boundary (`api/routes/pool_admin.py`)
- `_PoolHealthSnapshot` += `ingest_contradiction: bool = False` (extra="ignore" → legacy validates).
- `PoolHealthResponse` += `ingest_contradiction: bool = False`. `state` doc widened.
- OpenAPI dump + `gen.types.ts` regenerated (additive: `PoolHealthResponse.ingest_contradiction`).

## Frontend (`features/pool-admin/`)
- `lib.ts`: `AccountState` += `failing`; label "Failing"; badge variant `warning` (vs quarantined
  `danger`); `asAccountState` accepts it (unknown still → quarantined).
- `pool-health-table.tsx`: summary "{healthy} of {target} target healthy"; last-error column renders
  for `failing` too; `ingest_contradiction` alert banner (`data-testid="pool-ingest-contradiction-banner"`).

## How 119/120 build on this
- **TASK-119 (dynamic session store + revive)**: a revived account must visibly leave
  `failing`/`quarantined` → `healthy`. Revive should reset the read-outcome fields (so a re-minted
  session starts clean) — `note_read_success()` already does the reset; reuse it or reset directly on
  store-reload. The persistent quarantine (fingerprint set) is the existing eviction; 119 adds the
  re-mint path. `failing` stays observational until 119 — do NOT gate `acquire()` here.
- **TASK-120 (revive API + UI)**: the `failing` badge + `ingest_contradiction` banner are the UI the
  revive flow flips. The snapshot + `PoolHealthResponse.ingest_contradiction` are already the contract
  120 consumes; 120 adds the action endpoints, not new read shapes.

## Gate evidence
`make fmt/lint/typecheck` green; `make test` = 1117 passed; FE `tsc -b`/eslint/`vitest run` = 306 passed.
New tests: test_account_pool_failing.py(11), test_reader_read_outcome.py(3), +4 pool_health, +2
integration pool_admin, FE lib.spec.ts(4). Rotation invariant: test_account_pool_rotation.py +
test_auth_quarantine.py unchanged and passing.
