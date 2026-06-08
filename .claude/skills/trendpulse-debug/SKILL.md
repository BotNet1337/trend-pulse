---
name: trendpulse-debug
description: Debug stage for TrendPulse surgical changes — systematic root-cause analysis with persistent notes, triggered inside trendpulse-executor when verify fails or review returns blocking findings. Usable standalone ("разберись почему", "отладь", "trace this bug"). Returns root cause + minimal fix.
---

# TrendPulse Debug (conditional stage)

Invoked when something doesn't work: verify (G2) failed, or review surfaced a blocking defect. Scientific method, not guess-and-check. Keep persistent notes so the investigation survives a context reset.

## Do

<workflow>
  <step n="1" goal="Reproduce">
    <action>Reproduce the failure deterministically using the verify evidence (the failing request/test/log). Capture exact inputs + observed vs expected.</action>
  </step>
  <step n="2" goal="Hypothesize → test → narrow">
    <action>Form a ranked list of hypotheses. Test the cheapest discriminating one first. Use `make logs`, targeted reads, and minimal probes. Record each hypothesis + result in the task doc `debug_runs`.</action>
    <action>Check the usual TrendPulse traps: SQLAlchemy session not committed / detached instance after commit; pgvector dimension mismatch (embedding size ≠ column dim); Celery task args not JSON-serializable (pass ids, not ORM objects); Redis TTL in seconds not ms; missing `await` on a Telethon/async coroutine; `FLOOD_WAIT` not caught → no backoff/account rotation; timezone-naive `datetime` mixed with aware; broken `max_instances=1` / per-user queue assumption (batch ran in parallel).</action>
  </step>
  <step n="3" goal="Root cause">
    <action>Identify the single root cause with evidence. Distinguish "implementation bug" (→ fix in `do`) from "plan was wrong" (→ back to plan).</action>
  </step>
  <step n="4" goal="Minimal fix">
    <action>Propose (or apply, if executor delegated it) the smallest fix that addresses the root cause without widening scope. Add a regression test that fails before / passes after.</action>
  </step>
</workflow>

## Return (structured)

```
status: resolved | unresolved | needs-replan
root_cause: <one line, with file:line evidence>
classification: implementation-bug | wrong-plan
fix: <what to change, minimal>
regression_test: <added test that captures this>
notes_appended_to: debug_runs   # persistent trail in the task doc
```

If `unresolved` after this cycle, the caller HALTs and asks the user after 2 cycles total.
