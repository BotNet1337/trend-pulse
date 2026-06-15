---
id: TASK-105
title: Convert _read_one FLOOD_WAIT recursion to a bounded retry loop
status: backlog
owner: backend
created: 2026-06-15
updated: 2026-06-15
tags: [reliability, collector, telegram, flood-wait, backlog]
---

# TASK-105 — `_read_one` FLOOD_WAIT recursion → bounded loop (backlog)

> Spun off from TASK-101 (audit finding-6, LOW). `TelegramCollector._read_one`
> (`reader.py:214` and `:270`) recurses (`async for post in self._read_one(...)`) on each
> FLOOD_WAIT hint. Bounded in practice (pool cooldown → `AllAccountsFloodWaitError`, plus the
> `collect_tick` soft time limit), so not a live hang — but it is recursion, not iteration,
> and a pathological repeated-flood channel grows the coroutine/generator stack.

## Plan (when scheduled)
Rewrite `_read_one` as `for attempt in range(MAX_FLOOD_RETRIES + 1):` with `continue` on a
short-flood retry at both the entity-resolve and iterate sites, preserving: yield semantics,
quarantine-on-permanent-auth, success `report_success`, and the long-flood/all-flood abort.
Add `MAX_FLOOD_RETRIES` constant. Re-run the existing rotation/flood tests (they pin the current
behavior) + add a "repeated short floods stop after N" test.

## Why backlog
Hot ingest path; LOW severity (already bounded). Defer until it can get careful standalone testing,
not bundled into a batch.
