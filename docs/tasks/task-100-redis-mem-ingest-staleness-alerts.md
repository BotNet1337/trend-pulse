---
id: TASK-100
title: Alert rules — Redis-memory-near-cap & ingest-staleness ops self-alerts
status: in-progress
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "e88de61"
branch: "task/100-redis-mem-ingest-staleness-alerts"
tags: [reliability, observability, redis, ingest, alerting, ops]
---

# TASK-100 — Redis-memory & ingest-staleness ops alerts

> Track A (reliability) #4. Audit gap: `emit_redis_memory` MEASURES Redis used/maxmemory but
> never ALERTS, and there is NO alert when ingest stalls (pool dead / buffer not draining /
> collector wedged → no posts flowing). For a weeks-unattended run these are the two "silent
> death" signals: Redis creeping to the 224mb noeviction cap (broker write-rejection) and
> ingestion stopping. Both should fire a throttled ops self-alert via the existing `notify_ops`.

## Context
`observability/pool_health.py::notify_ops(reason, text, settings, redis)` already provides a
throttled (Redis SET NX EX, one key per reason), best-effort, never-raises ops Telegram alert —
reused here (the collector already uses it for pool health). `posts.fetched_at` (`default=utcnow`)
is the true ingestion timestamp; `MAX(fetched_at)` age = time since the last ingested post.

## Discussion
<!-- durable record -->
- Q: Redis-mem alert threshold? → A: `redis_memory_alert_ratio=0.9` (setting). Fire when
  `used/maxmemory >= 0.9` (only when maxmemory>0 — the prod cap is 224mb). 90% leaves headroom to
  act before noeviction starts rejecting broker writes. Validator: ratio ∈ (0, 1].
- Q: Ingest-staleness threshold? → A: `ingest_staleness_alert_seconds=1800` (30 min). Crypto-RU
  channels post constantly; 30 min with zero ingested posts = ingest broken (dead pool / undrained
  buffer / wedged collector), not a quiet period. No posts AT ALL (MAX is NULL, warming up) → NOT
  stale (don't alert on an empty cold start).
- Q: Query cost over weeks? → A: `SELECT MAX(fetched_at) FROM posts` is a single aggregate pass
  every 300s. No fetched_at index today; at current table size it's sub-100ms. NOTE a future
  `ix_posts_fetched_at` if the table grows large (backlog — relates to the audit's "rows grow").
- Q: Where do the alerts fire? → A: in `observability/tasks.py::emit_signal_latency_task` (the
  existing 300s metric tick), reusing its Redis client + a DB session. Pure decision helpers in
  `signal_latency.py` are unit-tested; the task wires `notify_ops`.
- Decision (owner-gated): ops alerts only send when `ops_telegram_*` configured (else silent no-op,
  existing behavior). Effective on prod after `make deploy`. Batched with Track A.

## Scope
- `backend/src/config.py` — `redis_memory_alert_ratio=0.9` (+validator ∈(0,1]), `ingest_staleness_alert_seconds=1800`.
- `backend/src/observability/signal_latency.py` — `is_redis_memory_critical(used, maxmemory, ratio)`
  (pure), `emit_ingest_staleness(session, settings) -> dict` (metric + `stale` flag).
- `backend/src/observability/tasks.py` — wire `notify_ops` for both: redis-mem-high + ingest-stale.
- `backend/tests/unit/test_signal_latency.py` (or new) — predicate + staleness + validator tests.

Touch ONLY the above. Do NOT touch: notify_ops itself, pool_health, the beat schedule, migrations.
Blast radius: one new ops-alert path off the existing 300s metric tick. Read-only DB. No schema/API.

## Acceptance Criteria
- [ ] **AC1 — redis-mem predicate.** `is_redis_memory_critical(used, maxmemory, ratio)` → True iff
  `maxmemory>0 and used/maxmemory >= ratio`; False when maxmemory<=0 (unbounded/dev).
- [ ] **AC2 — redis-mem alert.** When the metric shows used/maxmemory ≥ ratio, the task calls
  `notify_ops("redis_memory_high", …)` (throttled, aggregates-only text, no secrets).
- [ ] **AC3 — ingest staleness.** `emit_ingest_staleness` logs `ingest_staleness` (age_s, stale,
  threshold_s); `stale=True` iff a most-recent post exists AND its age ≥ threshold; NULL (no posts)
  → stale=False.
- [ ] **AC4 — ingest alert.** When `stale`, the task calls `notify_ops("ingest_stale", …)`.
- [ ] **AC5 — never raises.** Both alert paths are best-effort (wrapped like the existing metric
  parts); a DB/Redis error logs a warning and does not break the tick or the other metrics.
- [ ] **AC6 — runtime validator + green.** ratio∈(0,1] validator; `make ci-fast` green.

## Plan
1. (RED) tests: `is_redis_memory_critical` truth table; `emit_ingest_staleness` stale flag (mock
   session); ratio validator rejects 0/<0/>1.
2. (GREEN) config consts+fields+validator; signal_latency predicate + emit_ingest_staleness; wire
   notify_ops in tasks.py (best-effort parts).
3. verify (`make ci-fast`); review.

## Invariants
- `notify_ops` unchanged; alerts throttled per reason (no spam).
- Metric tick stays read-only and never raises (each part independently best-effort).
- Empty-corpus cold start must NOT alert ingest-stale (NULL MAX → not stale).

## Edge cases
- maxmemory=0 (dev, unbounded Redis) → never redis-mem-critical.
- No posts yet (fresh deploy) → MAX(fetched_at) NULL → not stale.
- Redis/DB down during the tick → warning, no alert, other metrics unaffected.

## Test plan
- Unit: predicate truth table; staleness stale/fresh/NULL; validator. `make ci-fast` green.
- Prod (post owner-deploy, batched): force a stale window (no ingest) → ops alert; observe
  redis_memory log ratio. Verified during the Track A batch-deploy.

## Review (adversarial, fresh-context) — WARN→resolved
0 critical/high. **MEDIUM ×2 fixed in-PR:** (1) added `ingest_staleness_alert_seconds > 0`
validator (+test); (2) `MAX(fetched_at)` seqscan (no index) → tracked as **TASK-104** (fetched_at
index, backlog) with a concrete code reference. **LOW addressed:** added task-level wiring tests
(notify_ops fires on critical/stale, silent when healthy) — the actual alert behavior was untested.
**LOW noted (acceptable):** reason slug `ingest_stale` vs log key `ingest_staleness`; global (not
per-tenant) ingest signal (system-wide ingest health is the intent). All correctness claims verified:
NULL→not stale, maxmemory<=0→not critical, empty-dict error path suppressed, notify_ops never raises,
throttles independent, alert text aggregates-only. Owner feedback: real types (isinstance narrowing,
no Any/cast); runtime validators for both new settings.

## Checkpoints
current_step: 6
baseline_commit: "e88de61"
branch: "task/100-redis-mem-ingest-staleness-alerts"
lock: "reliability-loop"
- [x] 1 locate (observability layer + notify_ops + posts.fetched_at)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: predicate + staleness + 2 validators + 3 task-wiring tests)
- [x] 4 verify (G2 — 962 unit pass, mypy clean, ruff clean)
- [x] 5 review (adversarial — MEDIUM×2 fixed, LOW addressed)
- [x] 5.5 security (skip — bind-param-free literal SQL, no user input, no secrets)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (batched, owner cycle)
