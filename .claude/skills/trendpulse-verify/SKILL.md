---
name: trendpulse-verify
description: Verify stage (G2) for TrendPulse surgical changes — FULL verification, not just tests. Runs tests + lint + typecheck + runtime health AND a real behavioral check (e.g. an actual API request against the running endpoint). Usable standalone ("проверь это изменение", "verify this") or dispatched by trendpulse-executor. Returns pass/fail with evidence.
---

# TrendPulse Verify (stage 4 / Gate G2)

The gate that proves the change actually works at runtime — **build passing ≠ runtime working**. Verification is incomplete until the changed behavior has been exercised for real.

## Do

> **Run sub-checks in parallel where independent:** static (1), tests (2), and runtime (3) have no ordering dependency — kick them off together and collect results, then do the behavioral check (4) which needs the running service. This shortens feedback time.

<workflow>
  <step n="1" goal="Static gates">
    <action>Run lint + typecheck (`ruff check .`, `mypy .`). Fail fast on errors.</action>
  </step>
  <step n="2" goal="Tests">
    <action>Run existing tests covering the touch points; run added/edited tests via make: unit (`make test`), integration against a test Postgres/Redis (`make test-integration`, which brings up deps + runs `pytest -m integration`), where the change demands it.</action>
  </step>
  <step n="3" goal="Runtime health">
    <action>`make restart` (or `make up-d`) for affected services, then confirm `Application startup complete` in `make logs`. No crash loops, no unhandled errors on boot.</action>
  </step>
  <step n="4" goal="REAL behavioral check (mandatory)">
    <critical>Exercise the actual change against the running system — do not rely on unit tests alone.</critical>
    <action>If an HTTP endpoint was added/changed: make a real request (curl/httpie) against the running FastAPI app, with auth where needed; assert status code, body shape, and side effects (Postgres row, enqueued Celery task, Redis key).</action>
    <action>If a Celery task/worker or collector changed: trigger the real task (`apply_async` / beat tick) or run the collector against a real public channel, and observe the effect in worker logs/DB/Redis.</action>
    <action>If a flow spans services: drive the end-to-end path and confirm the final state.</action>
    <action>Confirm every Acceptance Criterion (Given/When/Then) from the task doc holds against the real system. Verify invariants still hold.</action>
  </step>
</workflow>

## Surface → behavioral check matrix (mandatory check by change type)

| Change touches | Real check to run |
|---|---|
| HTTP endpoint (FastAPI) | `curl`/httpie real request to running API (with auth) → assert status + body + side-effects (Postgres row / enqueued Celery task / Redis key) |
| Celery task / worker | trigger the task (`apply_async` / beat tick) → observe handler effect in `make logs` + DB |
| Collector (Telethon) | run against a real public channel → assert posts buffered in Redis (respect rate limits) |
| Cross-service flow | drive the end-to-end path (collect → batch → score → alert) → confirm final state |
| DB schema / migration | apply the Alembic migration on a test DB → assert shape + a read/write round-trip (incl. pgvector dim) |
| Pipeline step (dedup/embed/cluster) | unit test + run the step on a sample post batch → assert output shape |
| Pure util / domain logic | unit tests suffice (no running service) — but still assert the AC |

## Return (structured)

```
status: pass | fail
static: { ruff, mypy }
tests: { unit, integration }   # counts + pass/fail
runtime: { started: bool, logs_evidence }
behavioral:
  - check: <what was exercised, e.g. "POST /watchlist → 201 + watchlist row + batch:user_{id} task enqueued">
    command: <actual request/trigger run>
    result: <observed status/body/side-effect>
    ac: <which Acceptance Criterion this proves>
failures: [{ where, what, evidence }]   # on fail → caller routes to debug
```
