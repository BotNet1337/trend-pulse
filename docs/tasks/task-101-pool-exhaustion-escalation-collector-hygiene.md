---
id: TASK-101
title: Repeating pool-exhaustion ops alert + collect-marker TTL
status: in-progress
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "e3ca8eb"
branch: "task/101-pool-exhaustion-escalation-collector-hygiene"
tags: [reliability, collector, telegram, ops, alerting, redis, ttl]
---

# TASK-101 — Pool-exhaustion escalation + collect-marker TTL

> Track A (reliability) #5. Two collector-hygiene fixes for a weeks-unattended run:
> (1) when the TG pool is FULLY exhausted (all sessions dead/quarantined) the only signal
> today is the per-account one-shot `auth_dead:{n}` alert at quarantine time — if the owner
> misses it, the pool stays dead silently. Add a REPEATING (throttled) `pool_exhausted` ops
> alert so the "re-mint sessions" nudge recurs. (2) The collect last-tick marker is written
> WITHOUT a TTL (audit finding-3) — the one ingest Redis key that never expires; give it a TTL.

## Context
`notify_ops` throttles per reason via Redis SET NX EX (`ops_alert_throttle_seconds`, 1h), so a
new reason `pool_exhausted` recurs at most hourly = the desired escalation cadence. `_resolve_since`
already falls back safely to `now - collect_lookback_seconds` (clamped to retention) if the marker
is absent, so a TTL'd marker that expires after a long outage is harmless. The new ingest-staleness
alert (TASK-100) also repeats hourly for a dead pool, but `pool_exhausted` is more precise +
actionable ("re-mint sessions" vs generic "ingest stalled") and fires immediately on exhaustion.

## Discussion
<!-- durable record -->
- Q: Where to fire the repeating pool-exhausted alert? → A: in `_acquire_ready_client` (reader.py),
  where `pool.acquire()` raises `PoolExhaustedError`. Reuse `_emit_health_best_effort(notify_reason=
  "pool_exhausted", …)` (throttled via notify_ops), then re-raise so the ref is skipped (the existing
  tasks.py catch handles the skip — unchanged).
- Q: Marker TTL value? → A: **`RAW_POST_TTL_SECONDS`** (48h, already imported in tasks.py). It equals
  the retention window `_resolve_since` clamps to, so an expired marker just triggers the existing,
  correct recent-window fallback. Survives any normal operation (ticks every 60s).
- Q: Also fix the `_read_one` FLOOD_WAIT recursion (audit finding-6)? → A: **No, deferred to backlog
  (TASK-105).** LOW severity (bounded in practice by pool cooldown / AllAccountsFloodWaitError + the
  collect-tick soft time limit); rewriting the hot ingest generator into a loop carries risk not worth
  it in this batch. Tracked separately.
- Decision (owner-gated): effective on prod after `make deploy`. Batched.

## Scope
- `backend/src/collector/telegram/reader.py` — import `PoolExhaustedError`; catch it in
  `_acquire_ready_client`, emit repeating `pool_exhausted` ops alert, re-raise.
- `backend/src/collector/tasks.py` — add `ex=RAW_POST_TTL_SECONDS` to the marker `redis.set`.
- tests: `test_collect_tick.py` (marker TTL) + a reader test (pool_exhausted alert + re-raise).

Touch ONLY the above. Do NOT touch: quarantine logic (TASK-102), `_read_one` flood path,
the tasks.py PoolExhaustedError skip, beat schedule.
Blast radius: one new throttled alert path + a TTL on one Redis key. No schema/API.

## Acceptance Criteria
- [ ] **AC1 — repeating pool-exhausted alert.** When `_acquire_ready_client` hits
  `PoolExhaustedError`, it calls `notify_ops("pool_exhausted", …)` (throttled → recurs hourly) and
  re-raises `PoolExhaustedError` (ref still skipped by the caller).
- [ ] **AC2 — marker TTL.** `collect_tick` writes `COLLECT_LAST_TICK_KEY` with
  `ex=RAW_POST_TTL_SECONDS`; value unchanged (`now.isoformat()`).
- [ ] **AC3 — safe expiry.** With the marker absent/expired, `_resolve_since` still returns the
  recent-window fallback (unchanged behavior — covered by existing tests).
- [ ] **AC4 — green.** `make ci-fast` green; no behavior change to the happy path.

## Plan
1. (RED) tests: marker set with `ex=RAW_POST_TTL_SECONDS`; `_acquire_ready_client` emits
   `pool_exhausted` + re-raises on PoolExhaustedError.
2. (GREEN) reader.py catch + alert + re-raise; tasks.py marker `ex=`.
3. verify (`make ci-fast`); review.

## Invariants
- PoolExhaustedError still propagates (ref skipped) — only an alert is added before re-raise.
- Alert throttled per reason — no spam; recurs at most hourly.
- Marker value semantics unchanged; only a TTL added.

## Edge cases
- Pool recovers (owner re-mints) before the throttle window ends → next acquire succeeds, no alert.
- Marker expires after >48h of no ticks → `_resolve_since` recent-window fallback (already safe).

## Test plan
- Unit: `test_collect_tick` marker `ex`; reader pool_exhausted alert+re-raise (mock pool/redis).
- `make ci-fast` green.
- Prod (post owner-deploy, batched): simulate exhausted pool → recurring ops alert; marker TTL via
  `redis-cli TTL collect:last_tick_at`.

## Review (inline adversarial — trivial, pattern-matching change)
Reuses the exact `_emit_health_best_effort`/`notify_ops` path used 4× already in reader.py +
mirrors TASK-076's buffer TTL. Verified: `PoolExhaustedError` and `AllAccountsFloodWaitError` are
SIBLINGS (both directly subclass `CollectorError`) → the new `except PoolExhaustedError` (ordered
first) cannot miscatch floods. Alert fires then re-raises (tested) → caller skips ref (unchanged).
Marker TTL confirmed via fakeredis `.ttl()`; expiry path covered by existing `_resolve_since` fallback
tests. Alert text aggregates-only (no secrets/sessions). A subagent review was not spawned for this
2-line-logic change given the established verified pattern; higher-risk tasks (098/099/100) got one.

## Checkpoints
current_step: 6
baseline_commit: "e3ca8eb"
branch: "task/101-pool-exhaustion-escalation-collector-hygiene"
lock: "reliability-loop"
- [x] 1 locate (reader._acquire_ready_client + tasks marker + notify_ops)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: pool_exhausted alert+reraise test, marker TTL test)
- [x] 4 verify (G2 — 963 unit pass, mypy clean, ruff clean)
- [x] 5 review (inline adversarial — sibling-exception ordering verified)
- [x] 5.5 security (skip — alert text aggregates-only, no secrets/SQL/input)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (batched, owner cycle)
