# Runbook — autonomous `/loop` for EPIC-ACCOUNT-AUTOPROVISION (TASK-129..137)

Autonomous run of **only** this epic's tasks (`task-129..137`) to `status: done`, one PR each,
**auto-merged** (no human confirmation — per the `trendpulse-loop-autonomy` decision). Verify is a
**real behavioural check** (`make ci-fast` + curl API scenarios + Playwright UI), not "it builds".

## How to run

1. Run from `apps/trendPulse` (trendpulse skills + hooks active).
2. Precondition: tasks `129..137` exist as `planned`; remote `origin` + `gh auth` ready (they are).
3. `/loop` (no interval, self-paced) + paste the orchestrator prompt below.

## Orchestrator prompt (paste after `/loop`)

> You are the autonomous orchestrator for **EPIC-ACCOUNT-AUTOPROVISION**. Working dir:
> `/Users/macbookpro16/work/botnet/apps/trendPulse`. Source of truth: frontmatter `status` +
> `Checkpoints` (`current_step`) in `docs/tasks/task-12{9}..13{7}.md`. Speak Russian. Obey
> `docs/CONVENTIONS.md` + `docs/architecture/`. **Scope is STRICTLY tasks 129–137** — ignore all
> other `task-*.md`. **Do NOT ask the owner anything** — resolve blockers yourself; only HALT if a
> blocker genuinely needs money/secret/external access that does not exist (real SMSPVA/Telegram is
> expected-gated and is NOT a blocker — use the fake provider path for verify).
>
> **ITERATION (exactly one task):**
> 1. **Pick.** Read `task-129..137` frontmatter + `tasks-index.md` Deps. Take the lowest-numbered
>    task with `status != done` whose deps are all `done`. None actionable + unfinished remain →
>    report blockage + HALT. All done → go to COMPLETION.
> 2. **Mark.** In the task doc: `status: in-progress`, `updated:` today, set Checkpoints `lock` = run id.
> 3. **Execute** via skill **`trendpulse-executor`** for that TASK-NNN: `do` (TDD RED→GREEN) →
>    `verify` (G2 — see below) → `review` (adversarial, different model) → `security` (5.5 if it
>    touches auth/input/secrets) → `ship`. Everything through `make`. Blocking verify/review/security
>    findings → `debug` (≤2 cycles), then re-verify.
> 4. **Verify (G2 — REAL scenarios, mandatory before ship):**
>    - `make ci-fast` green (ruff + mypy strict + pytest), `make openapi-drift-check` green if API changed.
>    - Bring the stack up locally (`make up` / needed services). Run **curl** scenarios from the
>      task's Acceptance Criteria against the live API (capture transcripts).
>    - For UI tasks, run **Playwright** against `/admin/pool` (capture screenshots/artifacts).
>    - Migrations apply **and** roll back.
>    - Paste the evidence into the PR + task `## Details`.
> 5. **Ship (one logical change = one PR).** Branch `gsd/phase-{NNN}-{slug}`, Conventional Commit
>    (code + docs together), `git push -u`, `gh pr create` (summary + verify evidence + AC checklist +
>    task link). Task doc → `status: review`, record `branch` + PR number.
> 6. **Auto-merge (NO confirmation).** When CI settles (only the two permanently-red checks
>    `depsec`/`openapi-drift` may remain → `gh pr merge --squash --admin --delete-branch`; otherwise
>    a normal squash-merge once required checks pass). Then: `status: done`, tick Checkpoints 6+7,
>    `current_step: done`, clear `lock`, update `tasks-index.md`, append `docs/learnings.md`.
> 7. **Next.** Brief summary → next actionable task.
>
> **RULES:** one task/iteration; respect deps; PR-flow only (never commit to `main` directly — the
> bash-guard hook blocks it); everything via `make`; never deploy from this worktree.
>
> **COMPLETION:** when `129..137` are all `done` → dispatch the **DoD-validator agent** (a fresh
> agent, different model) to walk every Acceptance Criterion across the epic against the live system
> (curl + Playwright) and emit a PASS/FAIL verdict per criterion with evidence. Then print the final
> table (task · PR · result · verify-evidence) and **end the loop** (no further wakeup).

## Task order (by deps)

`129 → 130 → 131 → 132 → 133 → 134 → 135 → 136 → 137`

## Notes

- Auto-merge differs from the generic `loop-execute-all-tasks.md` runbook (which pauses for
  confirmation): the owner pre-authorised full autonomy for this epic ("выполни всё сам до конца, не
  задавай вопросы") and the `trendpulse-loop-autonomy` memory records autonomous PR→merge.
- Activation is provider-driven (no `ACCOUNT_FACTORY_ENABLED`): `ACCOUNT_FACTORY_PROVIDER` unset → no-op,
  `fake` → local/CI (zero spend), `smspva` (+ `SMSPVA_API_KEY` from `.env`/vault) → live. The loop verifies
  the full scenario on the fake provider; the real SMSPVA path is smoke-tested via `balance()` (no spend)
  and the owner key is migrated to vault in TASK-137.
