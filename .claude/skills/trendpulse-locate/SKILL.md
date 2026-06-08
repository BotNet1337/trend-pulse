---
name: trendpulse-locate
description: Scope & Locate stage for TrendPulse surgical changes — find the minimal set of files/symbols/lines to touch and assess blast radius. Read-only. Usable standalone ("оцени радиус", "где это трогается", "scope this") or dispatched by trendpulse-executor as a subagent. Returns a scope statement + patterns + blast radius.
---

# TrendPulse Locate (stage 1)

Read-only reconnaissance. Bound the change before anyone edits anything — most over-editing starts by failing to scope.

## Do

<workflow>
  <step n="1" goal="Find minimal touch points">
    <action>Search by symbol/grep for entry points, call sites, and the owning layer (api / collector / pipeline / storage / alerts) in the project source (`api/`, `collector/`, `pipeline/`, `storage/`, `alerts/`).</action>
    <action>Read the relevant `docs/CODEMAPS/*` and `docs/CONVENTIONS.md` to place the change correctly.</action>
  </step>
  <step n="2" goal="Capture patterns at the edit site">
    <action>Note conventions the change must follow: naming, error handling, test style, imports, type hints, and the TrendPulse patterns in play (typed return values + explicit error handling — raise/handle a domain error at boundaries, never swallow; cross-module calls via service interfaces, not reaching into internals; Celery task contracts for async work; settings via pydantic-settings/env for TTL/URL/timeout — no magic literals; seconds as named constants; pure/immutable pipeline steps; Pydantic models validating at the API boundary).</action>
  </step>
  <step n="3" goal="Assess blast radius">
    <action>List consumers that could break: cross-module service interfaces, Celery tasks/queues (`docs/CODEMAPS/tasks.md`), DB schema / pgvector dimensions, public API request/response models.</action>
  </step>
  <step n="4" goal="Capture baseline">
    <action>Record `baseline_commit` = current repo HEAD (`git rev-parse HEAD`).</action>
  </step>
</workflow>

## Return (structured)

```
status: pass | blocked
scope:
  touch_only: [<file/symbol>, ...]
  do_not_touch: [<out of scope>, ...]
  blast_radius: [<consumers: service interfaces/Celery tasks/schema/public API>]
patterns: [<conventions to follow at this site>]
baseline_commit: <sha>
flag: <set if change spans >1 module or touches schema/events/public API — may not be surgical>
```

If `flag` is set, say so explicitly — the caller must surface it before proceeding.
