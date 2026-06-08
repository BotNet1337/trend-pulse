---
name: trendpulse-ship
description: Ship stage for TrendPulse surgical changes — first CONFIRMS the plan is fully executed (all checkpoints done, DoD + Acceptance Criteria met, diff within scope), then branches, makes a Conventional Commit, updates the task doc, and opens a PR. Usable standalone ("отгрузи", "сделай PR") or dispatched by trendpulse-executor as the final stage before learnings.
---

# TrendPulse Ship (stage 6)

Ship is a **gate first, action second**. Its job is to confirm the plan is actually done before anything leaves the working tree — then create the PR. CI is the final gate.

## Do

<workflow>
  <step n="1" goal="CONFIRM the plan is executed (gate)">
    <action>Read the task doc. Verify ALL of:</action>
    <action>— Checkpoints 1–5 are `[x]` (locate, plan, do, verify, review).</action>
    <action>— Every Acceptance Criterion (Given/When/Then) is satisfied, with verify evidence.</action>
    <action>— Every DoD item holds; review returned no unresolved CRITICAL/HIGH.</action>
    <action>— `git diff` vs `baseline_commit` is within the declared Scope (no files outside touch_only; no debug/format churn).</action>
    <check>If anything is unmet → STOP. Report the unmet items and return control to the relevant stage. Do NOT ship.</check>
  </step>
  <step n="2" goal="Branch + commit">
    <action>Create a branch: `gsd/phase-{N}-{slug}` (never commit to main).</action>
    <action>Make an atomic Conventional Commit (feat/fix/refactor/...) scoped to this change. End with the project's configured attribution rules.</action>
  </step>
  <step n="3" goal="Docs — same repo, same change">
    <critical>Code and docs live in ONE repo (`apps/trendPulse`, docs under `docs/`). Code + docs ship together in the same branch/PR.</critical>
    <action>In `docs/`: set task `status: review`, append iterative fixes/decisions to `## Details`, update `docs/tasks/tasks-index.md` (+ kanban `backlog.md` if present). Stage these alongside the code changes on the same branch.</action>
  </step>
  <step n="4" goal="Open PR">
    <action>Open the PR (summary, verify evidence incl. the real behavioral check, test plan, links to the task doc). CI is the final gate.</action>
  </step>
</workflow>

## Return (structured)

```
status: shipped | blocked
confirmation:
  checkpoints_complete: bool
  acceptance_criteria_met: bool
  dod_met: bool
  scope_clean: bool
  unmet: [<items>]            # populated when blocked
branch: <name>
commit: <sha + subject>
pr: <url>
```

On `blocked`, ship did NOT create anything — the caller fixes the unmet items first.
