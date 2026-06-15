---
id: TASK-097
title: Worker liveness healthcheck — Swarm restarts a hung-but-alive Celery worker
status: in-progress       # planned → in-progress → review → done
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "bba0bbe"
branch: "task/097-worker-liveness-healthcheck"
tags: [reliability, compose, celery, worker, healthcheck, swarm]
---

# TASK-097 — Worker liveness healthcheck

> Track A (reliability) #1. Reliability audit FM-3: `release/compose/worker.yml` has
> `restart_policy: condition: any` (restarts on crash/clean-exit) but **no `healthcheck`**.
> Swarm therefore cannot detect a HUNG-but-alive worker (deadlocked / wedged broker
> consumer) — it keeps the task "running" and the pipeline silently stops draining for
> the whole multi-week unattended window. Every other long-running service (api, redis,
> postgres, frontend, landing, templates) already has a healthcheck; the worker is the gap.

## Context

Goal of the owner: service runs WEEKS unattended, 100% stable. A wedged worker is one of
the top show-stoppers. Audit (2026-06-15, re-verified on origin/main bba0bbe): worker.yml
and beat.yml are the only services without a `healthcheck:` block. The worker runs
`celery -A celery_app worker -Q celery,batch,score:global -l info`. Celery exposes a
control-plane liveness probe — `celery -A celery_app inspect ping` — handled by the main
process even while prefork children execute long embed batches, so it stays responsive
under load. A failing Docker healthcheck marks the task unhealthy → Swarm reschedules it
(restart_policy `any` already in place) = automatic recovery from a hang.

Beat heartbeat is a SEPARATE mechanism (no `inspect` for beat) → TASK-098, not here.

## Discussion
<!-- durable record -->
- Q: Probe command? → A: `celery -A celery_app inspect ping -d celery@$$HOSTNAME --timeout 10`.
  Target the LOCAL node (`celery@<hostname>`, Celery's default nodename = `celery@%h`; Docker
  sets `$HOSTNAME` to the container id) so the healthcheck verifies THIS container's worker,
  not "any worker on the broker". `$$` escapes compose interpolation → shell expands at runtime.
  Default inspect timeout (1s) is too tight under load → `--timeout 10`.
- Q: start_period? → A: **90s**. The worker process boots fast and is pingable in ~10-20s;
  the ML model loads lazily on first embed, not at boot. 90s is a safe margin so a cold start
  never flaps the healthcheck.
- Q: interval/timeout/retries? → A: `interval: 30s`, `timeout: 15s`, `retries: 3` — three
  consecutive missed pings (~90s wedged) before unhealthy; conservative to avoid false kills
  of a momentarily busy control plane.
- Decision (owner-gated): takes effect on prod only after `make deploy` (rolling update of the
  worker service). Compose edit alone does not change prod.

## Scope

- `release/compose/worker.yml` — add a `healthcheck:` block (mirror the CMD-SHELL style of
  api.yml/frontend.yml).

Touch ONLY: `release/compose/worker.yml`.
Do NOT touch: worker command, networks, resources, restart_policy, any code, beat.yml.
Blast radius: prod worker service lifecycle only; no code, no schema, no API. CI compose-lint.

## Acceptance Criteria

- [x] **AC1 — healthcheck present.** `release/compose/worker.yml` defines a `healthcheck:` that
  runs `celery -A celery_app inspect ping -d celery@$$HOSTNAME --timeout 10` and exits non-zero
  on failure.
- [x] **AC2 — sane timings.** `interval: 30s`, `timeout: 15s`, `retries: 3`, `start_period: 90s`.
- [x] **AC3 — nothing else changed.** Diff touches only the healthcheck block (18 insertions);
  command, deploy, networks, restart_policy unchanged (`git diff --stat`).
- [x] **AC4 — valid compose.** `docker compose -f release/compose/worker.yml config -q` exits 0
  with env files stubbed (the only error without stubs is the gitignored generated deploy.env).
- [x] **AC5 — no CI drift.** Only YAML/markdown changed; Python tree untouched → `ci-fast`
  (ruff/mypy/pytest) outcome unchanged from baseline.

## Review (adversarial, fresh-context code-reviewer) — APPROVE
0 CRITICAL/HIGH/MEDIUM. Verified: `$$HOSTNAME` compose-escaping correct (Docker $HOSTNAME ==
celery `%h` nodename); `inspect ping` answered by prefork main process even during long embed
batches (stays green under load, red on main-process death/deadlock); 90s start_period covers
torch lazy-load (not at boot); stop-first/rollback/restart_policy interaction correct; `celery`
on PATH + `celery_app` importable from venv. **1 LOW (follow-up, not this scope):** probe detects
a dead MAIN process, not all-prefork-children-dead — complement with `task_time_limit`/
`task_soft_time_limit` on embed/batch tasks (collect-tick already has limits per audit). → queue follow-up.

## Plan

1. Add `healthcheck:` block to the `worker` service in `release/compose/worker.yml`.
2. Validate compose parses (`docker compose -f release/compose/worker.yml config`).
3. verify: `make ci-fast`; adversarial review.
4. ship → PR → merge.
5. Local verify (compose config) + prod deploy (`make deploy`) + prod manual test: confirm
   `docker service ps` shows the worker healthy and a forced `kill -STOP` of the worker process
   flips it to unhealthy → rescheduled.

## Invariants

- Worker command, queues, networks, resources, stop_grace_period, restart_policy UNCHANGED.
- Healthcheck targets the local node only (no cross-node false positives).
- noeviction Redis (TASK-076) unchanged — healthcheck adds only a lightweight control ping.

## Edge cases

- Cold start (model not loaded): `start_period: 90s` covers boot; ping responds before then.
- Worker busy with a long embed batch: prefork main process answers control ping → healthy.
- Broker briefly unreachable: ping fails, but `retries: 3` over 90s avoids a single-blip kill.

## Test plan

- `docker compose -f release/compose/worker.yml config` parses (compose validity).
- `make ci-fast` green.
- Prod (post owner-deploy): `docker service ps trendpulse_worker` healthy; STOP-signal the
  worker process → task flips unhealthy → Swarm reschedules. (Runtime proof, post-deploy.)

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 6
baseline_commit: "bba0bbe"
branch: "task/097-worker-liveness-healthcheck"
lock: "reliability-loop"
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [x] 3 do (edit compose — healthcheck block, 18 insertions)
- [x] 4 verify (G2 — `docker compose config -q` exit 0; YAML parse confirms block)
- [x] 5 review (adversarial fresh-context reviewer — APPROVE, 1 LOW follow-up)
- [x] 5.5 security (skip — no auth/input/secrets/SQL/public-API)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod deploy + manual verify (owner cycle — `make deploy`, then service-ps healthy + STOP-probe test)
