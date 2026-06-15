---
id: TASK-098
title: Beat heartbeat + healthcheck — detect a hung Celery beat scheduler
status: in-progress
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "89441ef"
branch: "task/098-beat-heartbeat-healthcheck"
tags: [reliability, compose, celery, beat, scheduler, healthcheck, redis]
---

# TASK-098 — Beat heartbeat + healthcheck

> Track A (reliability) #2. Audit FM-3: `beat` (the SINGLE scheduler, `replicas: 1` strict)
> has `restart_policy: any` but NO healthcheck. A hung-but-alive beat stops enqueuing EVERY
> periodic task (collect/batch/score/purge/resweep…) → the whole pipeline silently freezes
> for the unattended window. `inspect ping` only works for workers, not beat — beat needs a
> different liveness signal.

## Context

Worker liveness is TASK-097. Beat has no `inspect`; the robust beat-only signal is a heartbeat
the scheduler itself writes each tick. Approach: a `HeartbeatScheduler(PersistentScheduler)`
stamps a TTL'd Redis key `beat:heartbeat` on every `tick()`, then delegates to super. The TTL
(`beat_heartbeat_ttl_seconds`, default 600s) is GREATER than Celery beat's 300s `max_interval`
(beat wakes ≥ every 300s; with collect-tick at 60s it ticks ~every 60s) so a healthy beat always
refreshes the key, but a hung beat lets it expire. The beat container's Docker healthcheck checks
the key EXISTS (TTL = freshness, no clock math) → failing probe → Swarm reschedules (restart_policy
`any`). Heartbeat is written by BEAT ITSELF (not via the worker) so the signal is beat-only and
does not conflate worker health.

## Discussion
<!-- durable record -->
- Q: Why a custom scheduler vs the shelve-file mtime? → A: explicit, testable, and a clean
  beat-only signal; the shelve filename/sync cadence is fragile to depend on.
- Q: Why not a beat→worker→redis heartbeat task? → A: that conflates beat with worker liveness
  (worker down would falsely mark beat unhealthy). Beat writing its own key isolates the signal.
- Q: TTL value? → A: **600s** (`> max_interval 300s`), named `beat_heartbeat_ttl_seconds`.
  Healthy beat refreshes ≤300s; hung beat's key expires at 600s → detected within TTL + retries
  (~13 min). Acceptable for weeks-unattended; tighter would risk flapping at max_interval.
- Q: Redis write failure in tick()? → A: best-effort — must NEVER crash the scheduler loop
  (enqueuing tasks is more important than the heartbeat). Catch `redis.RedisError`, log a warning
  (not a bare `except`, not silent), then delegate to super().tick() regardless.
- Decision (owner-gated): effective on prod only after `make deploy` (rolling beat update). Batched
  with the rest of Track A (see loop doc) — one deploy, not per-PR.

## Scope
- `backend/src/config.py` — `_DEFAULT_BEAT_HEARTBEAT_TTL_SECONDS = 600` + field `beat_heartbeat_ttl_seconds`.
- `backend/src/scheduler.py` — `BEAT_HEARTBEAT_KEY` + `HeartbeatScheduler(PersistentScheduler)`.
- `release/compose/beat.yml` — beat command `--scheduler scheduler:HeartbeatScheduler` + healthcheck.
- `backend/tests/unit/test_scheduler.py` — tick() sets TTL'd key + delegates; Redis error tolerated.

Touch ONLY the above. Do NOT touch: beat_schedule entries, worker.yml, replicas:1 invariant, any task logic.
Blast radius: beat process only (scheduler subclass + its container healthcheck). No schema/API.

## Acceptance Criteria
- [ ] **AC1 — heartbeat on tick.** `HeartbeatScheduler.tick()` sets `beat:heartbeat` in Redis with
  `ex=beat_heartbeat_ttl_seconds`, then returns `super().tick()`'s value.
- [ ] **AC2 — TTL > max_interval.** `beat_heartbeat_ttl_seconds` default 600 (> 300s beat max_interval).
- [ ] **AC3 — fail-safe.** A `redis.RedisError` in the heartbeat write is logged (warning) and
  swallowed; `tick()` still delegates to super (scheduler keeps enqueuing).
- [ ] **AC4 — beat wired + probed.** `beat.yml` runs beat with `--scheduler scheduler:HeartbeatScheduler`
  and a `healthcheck` that exits non-zero when `beat:heartbeat` is absent.
- [ ] **AC5 — green.** `make ci-fast` green; `docker compose -f release/compose/beat.yml config -q` ok.

## Plan
1. (RED) test: `HeartbeatScheduler.tick()` calls `redis.set(BEAT_HEARTBEAT_KEY, ..., ex=ttl)` and
   returns super().tick(); a RedisError is swallowed + still delegates. Mock redis + super().tick.
2. (GREEN) config default+field; scheduler subclass (best-effort heartbeat → super).
3. beat.yml: `--scheduler` + python redis EXISTS healthcheck.
4. verify (`make ci-fast` + compose config), review.

## Invariants
- `replicas: 1` for beat UNCHANGED (a 2nd beat = double-enqueue).
- Heartbeat write never raises out of `tick()` — scheduling is never blocked by a Redis blip.
- TTL strictly > beat `max_interval` so a healthy beat never lets the key expire.

## Edge cases
- Redis briefly down: heartbeat write fails → logged, super().tick() still runs; key may expire →
  healthcheck retries (3×60s) absorb a short blip; a long Redis outage failing beat health is
  acceptable (Redis is the broker — beat can't enqueue anyway).
- Cold start: beat ticks immediately on boot → key set within seconds; `start_period 60s` covers it.

## Test plan
- Unit (`test_scheduler.py`): `test_heartbeat_scheduler_stamps_key_with_ttl`,
  `test_heartbeat_scheduler_tolerates_redis_error`, `test_beat_heartbeat_ttl_exceeds_max_interval`.
- `make ci-fast` green; `docker compose -f release/compose/beat.yml config -q` exit 0.
- Prod (post owner-deploy, batched): `docker service ps trendpulse_beat` healthy; STOP beat → key
  expires → unhealthy → rescheduled.

## Review + owner feedback (resolved)
- Adversarial fresh-context review: **APPROVE** (0 crit/high; 1 MEDIUM, 2 LOW). All 7 audited
  dimensions correct (`--scheduler` wiring, tick override semantics, RedisError catch-width,
  TTL math, healthcheck one-liner, single Redis client thread-safety, replicas:1 invariant).
- MEDIUM (detection latency 13min) → tuned healthcheck `interval 60s→30s`, `start_period 90s`
  (≈11min worst-case). LOW (no TTL validator) → added `@field_validator validate_beat_heartbeat_ttl`
  (runtime check: TTL must exceed `_BEAT_MAX_INTERVAL_SECONDS=300`). LOW (probe connection) → N/A:
  the probe is a short-lived `python -c` process that exits → no leak in beat.
- **Owner feedback (no `Any`):** replaced `*args: Any` with real `object` type in the tick/init
  overrides (no suppression, mypy-clean, Liskov-compatible). See [[no-any-prefer-real-types]].
- **Owner feedback (memory/resources):** HeartbeatScheduler creates ONE Redis client at init and
  reuses it across ticks (no per-tick connection churn); the Docker healthcheck runs a separate
  short-lived process that exits each probe → no accumulation in the beat process. Memory-clean.

## Checkpoints
current_step: 6
baseline_commit: "89441ef"
branch: "task/098-beat-heartbeat-healthcheck"
lock: "reliability-loop"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: 3 scheduler tests + 3 validator tests → code; all green)
- [x] 4 verify (G2 — 946 unit pass, mypy clean, ruff clean, beat.yml compose -q ok)
- [x] 5 review (adversarial — APPROVE; MEDIUM/LOW folded in)
- [x] 5.5 security (skip — no auth/input/secrets/SQL/public-API)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (batched, owner cycle)
