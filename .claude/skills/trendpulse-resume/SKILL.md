---
name: trendpulse-resume
description: Resume a paused/interrupted TrendPulse surgical change. Thin entry point — reads current_step from the task doc's Checkpoints and starts trendpulse-executor at exactly that stage. Use when the user says "продолжи операцию", "resume", or comes back to half-finished work after a context reset.
---

# TrendPulse Resume

A thin shim over `trendpulse-executor`. It does not do any work itself — it restores position and hands off.

## Do

<workflow>
  <step n="1" goal="Find the operation">
    <action>Locate the active task doc `docs/tasks/task-NNN-*.md` (the one with `status: in-progress` / unfinished Checkpoints). If ambiguous, ask which TASK-NNN.</action>
  </step>
  <step n="2" goal="Read state">
    <action>Read the Checkpoints block: `current_step`, which checkpoints are `[x]`, `baseline_commit`, `branch`, `debug_runs`.</action>
    <action>Sanity-check reality: is `branch` still checked out? does `baseline_commit` still exist? Note drift.</action>
  </step>
  <step n="3" goal="Hand off to executor">
    <action>Invoke `trendpulse-executor` entering at `current_step`. Executor must NOT redo completed checkpoints.</action>
  </step>
</workflow>

## Return

```
resumed: TASK-NNN
entered_at: <current_step>
completed: [<checkpoints already [x]>]
drift: <none | branch missing | baseline moved | ...>
```
