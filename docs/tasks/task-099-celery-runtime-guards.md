---
id: TASK-099
title: Celery runtime memory/hang guards — child recycling + task time limits + result TTL
status: in-progress
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "d94f6eb"
branch: "task/099-celery-runtime-guards"
tags: [reliability, celery, memory, worker, timeouts, redis, oom]
---

# TASK-099 — Celery runtime memory/hang guards

> Track A (reliability) #3, **highest-impact** — from the 2026-06-15 owner-requested
> memory/resource audit. Two CRITICALs for a weeks-unattended run, both in `celery_app.conf`:
> (1) the worker child is NEVER recycled (no `worker_max_tasks_per_child`) → torch/native
> memory creeps with no ceiling → eventual OOM (the #1 "degrades after weeks" cause);
> (2) `run_user_batch`/`score_tick`/most tasks have NO time limit (only `collect_tick` does)
> → a stuck embed / pgvector NN query pins a worker slot FOREVER. Plus MEDIUM: `result_expires`
> unset → result-backend churn on the 224mb noeviction Redis (the historical OOM symptom).

## Context
Audit verified: embedding model is a process-global singleton, all Redis keys are TTL'd
(except the collect marker — TASK-101), DB sessions are context-managed, HTTP clients reused.
The remaining structural risks are Celery runtime config. This task sets them as named,
validated settings (no magic literals — CONVENTIONS).

## Discussion
<!-- durable record -->
- Q: `worker_max_tasks_per_child` value? → A: **250** (setting, tunable). Recycling reloads the
  ~90MB MiniLM model per child, so not too low; 250 tasks ≈ recycle every ~15-20 min at the
  current tick cadence — amortizes the reload while bounding creep.
- Q: Set `worker_max_memory_per_child` too? → A: **NO, deferred.** Sizing it safely needs real
  prod child RSS (baseline ≈1.5GB per the audit); a guessed cap thrashes. `max_tasks_per_child`
  already bounds creep; memory-cap is a prod-tuning follow-up after measuring RSS on deploy.
- Q: `worker_concurrency`? → A: set explicitly to **2** (setting), matching `worker.yml` cpus:2.0.
  Celery defaults to `os.cpu_count()` of the HOST (ignores the cgroup cpu limit) → on a many-core
  host it would fork many children, each lazily loading its own model copy → OOM. Pinning it is a
  real memory guard. Default 2; tunable if prod sizing changes.
- Q: Global time limits vs per-task? → A: global `task_soft_time_limit=900`/`task_time_limit=1200`
  (settings). Per-task decorator limits (collect_tick) OVERRIDE the global, so collect keeps its
  own; the global covers run_user_batch/score_tick/etc. Generous (15/20 min) so a legit batch is
  never killed (with acks_late a wrongful kill would redeliver+loop), tight enough to catch a hang.
  soft raises SoftTimeLimitExceeded (catchable); hard SIGKILLs the child (recycles it).
- Q: `result_expires`? → A: **3600s** (setting). Results are largely ignored; default 24h on the
  shared 224mb noeviction Redis competes with the raw buffer. Short TTL bounds result-meta churn.
- Q: Wire `worker_process_shutdown`→`aclose()` (audit finding 5)? → A: **deferred.** On child exit
  the OS closes all fds/sockets, so recycling does not leak fds; graceful aclose is a minor nicety.
  Backlog, not this scope.
- Decision (owner-gated): effective on prod after `make deploy` (rolling worker update). Batched.

## Scope
- `backend/src/config.py` — 5 `_DEFAULT_*` consts + fields: `celery_worker_concurrency=2`,
  `celery_worker_max_tasks_per_child=250`, `celery_task_soft_time_limit_seconds=900`,
  `celery_task_time_limit_seconds=1200`, `celery_result_expires_seconds=3600` + a `@field_validator`
  enforcing `soft < hard`.
- `backend/src/celery_app.py` — wire the five into `celery_app.conf`.
- `backend/tests/unit/test_celery_config.py` — assert conf sourced from settings + validator.

Touch ONLY the above. Do NOT touch: task logic, routing, beat schedule, worker.yml command,
collect_tick's own per-task limits, worker_max_memory_per_child (deferred).
Blast radius: worker/beat runtime behavior (recycling cadence, task kill-on-timeout, result TTL).
No schema/API. CI: unit + mypy.

## Acceptance Criteria
- [ ] **AC1 — child recycling.** `celery_app.conf.worker_max_tasks_per_child == settings.celery_worker_max_tasks_per_child` (250).
- [ ] **AC2 — concurrency pinned.** `celery_app.conf.worker_concurrency == settings.celery_worker_concurrency` (2).
- [ ] **AC3 — task time limits.** `task_soft_time_limit`/`task_time_limit` sourced from settings (900/1200), soft < hard.
- [ ] **AC4 — result TTL.** `result_expires == settings.celery_result_expires_seconds` (3600).
- [ ] **AC5 — runtime validator.** A `@field_validator` rejects `celery_task_soft_time_limit_seconds >= celery_task_time_limit_seconds` at startup.
- [ ] **AC6 — green.** `make ci-fast` green (mypy, ruff, 949+ unit).

## Plan
1. (RED) tests in `test_celery_config.py`: conf values == settings; soft<hard validator rejects bad.
2. (GREEN) config consts+fields+validator; wire `celery_app.conf` (concurrency, max_tasks_per_child,
   task_soft_time_limit, task_time_limit, result_expires).
3. verify (`make ci-fast`); review.

## Invariants
- `task_acks_late=True` UNCHANGED — a hard-killed/redelivered task must stay idempotent (per-user
  lock + idempotent drain already guarantee this; the generous hard limit avoids killing legit work).
- Per-task `soft_time_limit`/`time_limit` (collect_tick) still override the global.
- Recycling reloads the model per child — acceptable at 250 tasks; never 1 (thrash).

## Edge cases
- A legit long batch near the hard limit: limits are generous (20 min) vs sub-minute real batches.
- Soft limit raises `SoftTimeLimitExceeded` inside the task — existing tasks don't catch it, so it
  propagates → task fails → (acks_late) redelivers; idempotency makes the re-run safe.
- Host with !=2 cores: concurrency pinned to the setting, not host CPU count (intended).

## Test plan
- Unit (`test_celery_config.py`): conf == settings for all five; validator rejects soft>=hard.
- `make ci-fast` green.
- Prod (post owner-deploy, batched): `celery -A celery_app inspect stats` shows
  `max-tasks-per-child`/`pool` concurrency; observe child recycling in worker logs; measure child
  RSS to size a future `worker_max_memory_per_child`.

## Review (adversarial, fresh-context) — resolved
- **HIGH (fixed):** new `task_time_limit=1200s` exceeded `batch_lock_ttl_seconds=600s` → a
  hard-killed (SIGKILL, no `finally`) `run_user_batch` could outlive its per-user lock and let a
  redelivery/next-tick run the same user concurrently. Fix: `_DEFAULT_BATCH_LOCK_TTL_SECONDS`
  600→**1260** (> hard limit) + extended validator enforces `batch_lock_ttl >= task_time_limit`
  (runtime check). +2 tests.
- **MEDIUM (addressed):** added a `worker.yml` comment that concurrency is governed by the setting,
  not a `-c` flag (prevents silent drift).
- **LOW (confirmed safe):** model singleton reloads cleanly per recycled child; Telethon reconnect
  on recycle == normal restart (no AuthKeyDuplicated risk, single-pool-session); `result_expires`
  breaks nothing (no prod code calls `.get()`/chord/group — only test code); `SoftTimeLimitExceeded`
  propagates → lock released in `finally` → clean redelivery.
- Owner feedback honored: real types (no `Any`); runtime validators for both invariants.
- Deferred (backlog): `worker_max_memory_per_child` (needs prod RSS — measure on deploy);
  `worker_process_shutdown`→`aclose()` (process exit already frees fds).

## Checkpoints
current_step: 6
baseline_commit: "d94f6eb"
branch: "task/099-celery-runtime-guards"
lock: "reliability-loop"
- [x] 1 locate (audit + celery_app.py + config patterns)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (TDD: 7 tests → conf wiring + 2 validators)
- [x] 4 verify (G2 — 953 unit pass, mypy clean, ruff clean)
- [x] 5 review (adversarial — HIGH fixed, MEDIUM addressed, LOWs confirmed)
- [x] 5.5 security (skip — no auth/input/secrets/SQL/public-API)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (batched, owner cycle)
