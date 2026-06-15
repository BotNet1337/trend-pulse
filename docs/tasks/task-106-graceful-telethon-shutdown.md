---
id: TASK-106
title: Graceful Telethon/httpx disconnect on worker-process shutdown (restart-fragility mitigation)
status: review
owner: backend
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "8b3294f"
branch: "task/106-graceful-telethon-shutdown"
tags: [reliability, collector, telegram, shutdown, authkey, recycling]
---

# TASK-106 — Graceful disconnect on worker-process shutdown

> Post-incident (2026-06-15) restart-fragility mitigation (audit finding-5, previously deferred
> from TASK-099). A prefork child exits on `worker_max_tasks_per_child` recycle (TASK-099) or
> worker stop. Without a clean MTProto disconnect, the NEXT child reconnecting the SAME Telegram
> session can trigger `AuthKeyDuplicatedError` ("used from two places") → the session is
> permanently invalidated → on a small/single pool, ingest stops. The incident
> (`cache/INCIDENT-2026-06-15-deploy-authkey.md`) was a vault swap, but it surfaced this
> reconnect-fragility class; recycling now makes child exits frequent, so wiring graceful
> disconnect is overdue.

## Discussion
- Q: Which signal? → A: **`worker_process_shutdown`** (fires IN the prefork child on exit —
  recycle and stop), where the per-process `_loop` + cached Telethon clients live. (`worker_shutdown`
  is the main process, wrong scope.)
- Q: aclose via the protocol or hasattr? → A: added `aclose()` to the `SourceCollector` Protocol
  (all 3 impls already have it) — real-typed, no hasattr/Any.
- Q: SIGKILL (hard time limit)? → A: a SIGKILL skips Python cleanup, so the handler won't run then —
  acceptable; it covers the COMMON graceful exits (recycle + SIGTERM). Best-effort throughout.
- Note: this REDUCES but does not eliminate AuthKeyDuplicated; the real fixes are pool>=3 (TASK-103)
  and the vault-guard (TASK-107). Recycling cadence (max_tasks_per_child=250) left as-is; graceful
  disconnect makes it safe enough — revisit if reconnect churn shows up on a small pool.

## Scope
- `backend/src/collector/base.py` — declare `aclose()` on the `SourceCollector` Protocol.
- `backend/src/collector/registry.py` — `cached_collectors()` (already-built instances only).
- `backend/src/collector/tasks.py` — `@worker_process_shutdown.connect` handler: aclose each cached
  collector on `_loop`, then close `_loop`; best-effort (never raises).
- `backend/tests/unit/collector/test_worker_shutdown.py` — closes+loop, tolerates aclose error, no-loop no-op.

Do NOT touch: collect/read/quarantine logic, recycling config.
Blast radius: worker-process shutdown path only. No schema/API/prod-route.

## Acceptance Criteria
- [x] **AC1** — `worker_process_shutdown` handler aclose()s every cached collector on the per-process loop, then closes the loop.
- [x] **AC2** — best-effort: an aclose error (or loop-close error) is logged, never raised out of shutdown.
- [x] **AC3** — no loop / no collectors → clean no-op (a child that never collected closes nothing).
- [x] **AC4** — `aclose()` on the SourceCollector Protocol; all impls comply (mypy green).
- [x] **AC5** — `make ci-fast` green (974 unit).

## Test plan
- Unit: closes-collectors+loop; tolerates-aclose-error; no-loop-no-op. mypy + ruff green; 974 unit pass.
- Prod: verified only after the owner restores sessions (with the vault-guard, TASK-107) — observe
  fewer AuthKeyDuplicated across worker restarts/recycles.

## Checkpoints
current_step: 6
baseline_commit: "8b3294f"
branch: "task/106-graceful-telethon-shutdown"
lock: "reliability-loop"
- [x] 1 locate (signals, registry cache, per-process loop)
- [x] 2 plan (G1 — minimal)
- [x] 3 do (handler + protocol + accessor + 3 tests)
- [x] 4 verify (G2 — 974 unit, mypy, ruff green)
- [x] 5 review (inline adversarial — correct signal, best-effort, protocol compliance)
- [x] 5.5 security (skip — no auth/input/secrets/SQL/public-API)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
- [ ] 8 prod verify (after owner session restore + vault-guard)
