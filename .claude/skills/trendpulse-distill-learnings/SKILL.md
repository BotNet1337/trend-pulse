---
name: trendpulse-distill-learnings
description: Periodically distill the TrendPulse learnings ledger (docs/learnings.md) into durable agent memory. Promotes recurring/high-value lessons and decisions into feedback_*/project_* memory files (with Why + How to apply), updates MEMORY.md, and marks promoted ledger entries so it stays idempotent. Use when the user says "дистилляция уроков", "distill learnings", "promote learnings", or when the SessionStart nudge fires (≥5 unpromoted entries). Can be scheduled via /schedule or /loop.
---

# TrendPulse Distill Learnings (C15)

Turns the append-only ledger `docs/learnings.md` into compounding agent memory. Per-task lessons live in the vault; the ones that generalize must become `feedback_*`/`project_*` memory so they shape future sessions automatically. This is the periodic promotion step.

Memory dir: `/Users/macbookpro16/.claude/projects/-Users-macbookpro16-work-botnet-apps-trendPulse/memory/` (index `MEMORY.md`).

## Idempotency convention

A ledger block is "promoted" once it carries a trailing HTML comment:
```
<!-- promoted: feedback_xxx, project_yyy (YYYY-MM-DD) -->
```
This skill only processes blocks WITHOUT that marker, and adds it after promotion. The SessionStart hook counts unmarked blocks to decide when to nudge.

## Do

<workflow>
  <step n="1" goal="Read the ledger + existing memory">
    <action>Read `docs/learnings.md`. Collect blocks (each starts with `## <date> — TASK-NNN …`) that have NO `<!-- promoted` marker.</action>
    <action>Read the memory dir + `MEMORY.md` to know what already exists (avoid duplicates).</action>
    <check>If there are no unpromoted blocks → report "nothing to distill" and stop.</check>
  </step>

  <step n="2" goal="Select what generalizes">
    <critical>Promote only durable, reusable knowledge — not task-specific trivia. A lesson qualifies if it would change how you work on a FUTURE, unrelated task.</critical>
    <action>From the unpromoted blocks, pick: recurring gotchas (seen ≥2×), architectural/convention decisions, traps with a clear "how to apply", and corrections of prior assumptions.</action>
    <action>Drop one-off, task-only details (those stay in the ledger / task `## Details`).</action>
  </step>

  <step n="3" goal="Promote to memory (dedupe-aware)">
    <action>For each selected lesson, find an existing memory it belongs to (by description) and UPDATE it; otherwise CREATE a new file.</action>
    <action>Type: `feedback` for how-to-work rules (include **Why** + **How to apply**), `project` for project state/decisions, `reference` for pointers. Frontmatter: name (kebab-case), description (one line for recall), metadata.type.</action>
    <action>Link related memories with `[[name]]`. Add a one-line pointer to `MEMORY.md` (`- [Title](file.md) — hook`).</action>
  </step>

  <step n="4" goal="Mark ledger blocks promoted (idempotent)">
    <action>Append `<!-- promoted: <memory-names> (<today>) -->` to each block that was promoted. Leave blocks that were intentionally skipped UNmarked only if they may promote later; if a block is pure task-trivia, mark it `<!-- promoted: n/a (<today>) -->` so it isn't re-evaluated forever.</action>
    <action>Commit the `docs/learnings.md` change in the `docs` repo (Conventional Commit `docs: distill learnings → memory`).</action>
  </step>

  <step n="5" goal="Report">
    <action>Summarize: how many blocks processed, which memories created/updated, which skipped and why.</action>
  </step>
</workflow>

## Scheduling (optional)

This is a command, not a stage of executor. To run it periodically:
- **Nudge (built-in):** the SessionStart hook (`trendpulse-session-state.js`) counts unpromoted ledger blocks and suggests running this skill when there are ≥5.
- **Cron:** `/schedule` a routine that invokes this skill weekly.
- **Loop:** `/loop` for an ad-hoc cadence.

## Return

```
processed: <n blocks>
created: [feedback_*, project_*]
updated: [...]
skipped: <n> (task-trivia)
```
