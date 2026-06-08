---
name: trendpulse-review
description: Review stage for TrendPulse surgical changes — adversarial review of the diff against project CONVENTIONS and codemaps. Runs automatically after verify inside trendpulse-executor, and is usable standalone ("отревьюй diff", "review this code"). Triages findings by severity. Best run by a different model than the one that wrote the code.
---

# TrendPulse Review (stage 5, automatic after verify)

Adversarially review the change. Assume bugs and convention violations exist until proven otherwise. Three lenses, applied to the diff against `baseline_commit`.

## Lenses

1. **Conventions Auditor** — check against `docs/CONVENTIONS.md` (`## Forbidden Patterns`) and the hard rules: full type hints (no bare `Any`, no `# type: ignore`), functions small and single-purpose, explicit domain-error handling (raise/handle at boundaries, never a bare `except: pass`), cross-module via service interfaces (no reaching into another module's internals), Celery task args JSON-serializable (ids, not ORM objects), no magic TTL/URL/timeout literals (use pydantic-settings/env), seconds as named constants, pure/immutable pipeline steps, no stubs, Pydantic models validate at the API boundary.
2. **Edge Case Hunter** — walk every branch/boundary the diff introduces: None/empty, concurrency (per-user `max_instances=1`), partial failure, idempotency, `FLOOD_WAIT` / rate-limit handling, Celery retry/visibility, task ordering.
3. **Blind Hunter** — correctness bugs independent of conventions: wrong logic, broken invariants, missed consumers from the blast radius, scope creep (files touched outside the declared scope).

## Do

<workflow>
  <step n="1" goal="Get the diff and the contract">
    <action>Read `git diff` vs `baseline_commit` and the task doc (Scope, Plan, Invariants, Acceptance Criteria).</action>
  </step>
  <step n="2" goal="Apply the three lenses">
    <action>Run each lens over the diff. Cite `file:line` for every finding.</action>
  </step>
  <step n="3" goal="Triage">
    <action>Classify each finding: CRITICAL / HIGH / MEDIUM / LOW. CRITICAL/HIGH are blocking.</action>
  </step>
</workflow>

## Return (structured)

```
status: pass | blocked          # blocked if any CRITICAL/HIGH
verdict: <one line>
findings:
  - severity: CRITICAL|HIGH|MEDIUM|LOW
    lens: conventions|edge-case|blind
    where: <file:line>
    what: <the problem>
    fix: <concrete remedy>
scope_adherence: <ok | files touched outside scope: [...]>
```

On `blocked`, the caller routes to `debug`/`do` to fix, then re-verifies.
