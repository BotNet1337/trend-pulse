---
name: trendpulse-plan
description: Produce a surgical change plan for the TrendPulse monorepo, written into the docs vault as a task doc with checkpoints. Use when the user says "составь план", "plan this", "распиши задачу", "make a plan", or wants the approach scoped and approved BEFORE any code is written. Pairs with trendpulse-executor — plan first, then execute. NOT for greenfield features (use the full BMM planning flow).
---

# TrendPulse Plan

Produces the **planning half** of a surgical change: scope, locate, study patterns, write a minimal plan, and shrink it (gate G1) — then persist it as a **task doc in the docs vault** so `trendpulse-executor` can execute and resume from it.

Prime directive (inherited): **plan the smallest diff that satisfies the goal.** No scope creep on paper either.

## Where things live (docs vault — `docs/` inside the `apps/trendPulse` repo)

- **Task / plan docs:** `docs/tasks/task-NNN-slug.md` (lowercase, zero-padded NNN). Reuse an existing task doc if the work maps to one; otherwise create the next number.
- **ADRs (durable decisions):** `docs/architecture/adr-NNN-slug.md`.
- **Codemaps / conventions to read first:** `docs/CODEMAPS/*`, `docs/CONVENTIONS.md`, neighboring modules in the project source (`api/`, `collector/`, `pipeline/`, `storage/`, `alerts/`).
- **Index:** add/update the row in `docs/tasks/tasks-index.md`.

## Workflow

<workflow>

  <step n="1" goal="Read context — docs vault is the source of truth">
    <critical>The docs vault is authoritative for product + architecture. Read before planning; do not derive patterns from general knowledge.</critical>
    <action>Read `docs/CLAUDE.md`, the relevant `docs/CODEMAPS/*`, `docs/CONVENTIONS.md`, and any existing matching `docs/tasks/task-NNN-*.md` / ADR.</action>
    <action>Restate the goal in one sentence and the explicit Definition of Done.</action>
  </step>

  <step n="1.5" goal="Discuss — clarify ambiguities and record everything">
    <critical>Do not plan on assumptions. Surface what's unclear and get answers before scoping.</critical>
    <action>Detect ambiguities, missing requirements, product/UX decisions, and trade-offs only the user can resolve. List them.</action>
    <ask>Ask the user focused questions for each open item (adaptive — only what's genuinely unresolved; skip anything with an obvious default). One round if possible.</ask>
    <action>Record EVERYTHING in the task doc `## Discussion` section: each question, the answer, and the resulting decision + rationale. This is the durable record the rest of the plan builds on.</action>
    <check>If a decision is architectural/durable → note it for an ADR (`docs/architecture/adr-NNN-*.md`) during learnings.</check>
  </step>

  <step n="2" goal="Scope &amp; Locate — minimal touch points + blast radius">
    <action>Dispatch a read-only Explore subagent to find the MINIMAL set of files/symbols/lines to change. Keep the search out of the main context.</action>
    <action>Assess blast radius: consumers via service interfaces, Celery tasks/queues, DB schema / pgvector dimensions, public API request/response models.</action>
    <action>Write the scope statement: "Touch ONLY: [list]. Do NOT touch: [out of scope]."</action>
    <check>If the change spans &gt;1 module or touches schema/events/public API — flag it; this may not be surgical. Surface to the user.</check>
  </step>

  <step n="3" goal="Load patterns at the edit site">
    <action>Capture the conventions the change must follow: naming, error handling, test style, imports, type hints, and the TrendPulse patterns in play (typed return values + explicit domain-error handling — never swallow; cross-module via service interfaces; Celery task contracts for async work; settings via pydantic-settings/env for TTL/URL/timeout — no magic literals; seconds as named constants; pure/immutable pipeline steps; Pydantic validation at the API boundary).</action>
  </step>

  <step n="4" goal="Write the plan — minimal, ordered, testable">
    <action>For each touch point: file path + specific action, ordered by dependency.</action>
    <action>Write Acceptance Criteria in Given/When/Then.</action>
    <action>List invariants that MUST hold (data integrity, event emission, per-module error code ranges, no broken consumers).</action>
    <action>Enumerate edge cases + handling.</action>
    <action>Plan tests: which existing tests cover this, which to add/edit (unit / integration / e2e).</action>
  </step>

  <step n="5" goal="Shrink the diff — self-review (Gate G1)">
    <action>Adversarially review the plan: Can it be smaller? Unnecessary touch points? All edge cases covered? Any invariant unprotected? Cut everything non-essential.</action>
    <check>GATE G1 — plan minimal, correct, complete? If not, revise here before writing the doc.</check>
  </step>

  <step n="6" goal="Persist the plan as a task doc with checkpoints">
    <action>Create or update `docs/tasks/task-NNN-slug.md` using the structure below. Set frontmatter `status: planned`, `updated:` to today.</action>
    <action>Capture `baseline_commit` = current HEAD of the repo (e.g. `git rev-parse HEAD`), for safe rollback/resume.</action>
    <action>Add the **Checkpoints** block with `current_step: 3` and stages 1–2 (`locate`, `plan`) ticked `[x]` — so executor begins at `do` and can resume.</action>
    <action>Update `docs/tasks/tasks-index.md`.</action>
    <action>Tell the user the plan is ready and that `trendpulse-executor` can now run it (or run executor planless to skip this).</action>
  </step>

</workflow>

## Task-doc structure (the plan artifact)

```markdown
---
id: TASK-NNN
title: <short title>
status: planned        # planned → in-progress → review → done
owner: backend|frontend|infra
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
baseline_commit: <sha> # repo HEAD at plan time
branch: ""             # set by executor at ship time
tags: [..]
---

# TASK-NNN — <title>

> <one-line intent>

## Context
<why; links to codemaps/ADRs>

## Goal
<the outcome / DoD in prose>

## Discussion
<!-- filled in the discuss step; the durable record of clarifications -->
- Q: <question> → A: <answer> → Decision: <what> (rationale: <why>)

## Scope
- Touch ONLY: <files/symbols>
- Do NOT touch: <out of scope>
- Blast radius: <consumers: service interfaces/Celery tasks/schema/public API>

## Acceptance Criteria
- [ ] Given … When … Then …

## Plan
1. `path/to/file` — <action>
2. …

## Invariants
- <must hold after change>

## Edge cases
- <case> → <handling>

## Test plan
- unit: … / integration: … / e2e: …

## Checkpoints
<!-- trendpulse-executor reads current_step and ticks these; enables resume -->
current_step: 3
baseline_commit: <sha>
branch: ""
lock: ""
- [x] 1 locate (scope + patterns + blast radius)
- [x] 2 plan (G1 — minimal, approved)
- [ ] 3 do (TDD: failing test → minimal code)
- [ ] 4 verify (G2 — tests + runtime + real behavior)
- [ ] 5 review (auto, adversarial)
- [ ] 5.5 security (if touches auth/input/secrets/OAuth)
- [ ] 6 ship (confirm plan done → PR(s))
- [ ] 7 learnings (auto)
debug_runs: []

## Details
<!-- executor appends iterative fixes + decisions here -->
(initial)
```

`trendpulse-plan` completes stages 1–2, so it writes them `[x]` and sets `current_step: 3`. Hand off to `trendpulse-executor`, which begins at `do`. The remaining stages (verify, review, ship, learnings — and debug on demand) are run by executor as dispatched agents.
