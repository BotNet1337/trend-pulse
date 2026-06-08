---
name: trendpulse-executor
description: Orchestrates a surgical, targeted code change in the TrendPulse monorepo by dispatching stage-agents (locate, do, verify, review, debug, ship, learnings) — each in its own session — and assembling them into one unified flow. Use when the user gives a precise ticket ("fix this", "patch this bug", "implement this small change"), or says "execute the plan" / "run executor". Runs with a trendpulse-plan task doc (preferred) or planless. Tracks checkpoints + current_step in the task doc for resume. NOT for greenfield features (use the full BMM flow).
---

# TrendPulse Executor (orchestrator)

Executor is the **conductor**, not the worker. It owns one surgical change and drives it to done by **dispatching each stage as a separate subagent** (its own session/context), collecting a structured result, ticking the checkpoint, advancing `current_step` in the task doc, and moving to the next stage. The prime directive stays: **touch the minimum number of files/lines** — no scope creep.

There are only **two top-level commands**: `trendpulse-plan` and `trendpulse-executor`. Everything else (`locate`, `verify`, `review`, `debug`, `ship`, `resume`, learnings) are **stages** that executor invokes as agents.

## Stage pipeline

```
1 locate ─► 2 plan(G1) ─► 3 do(TDD) ─► 4 verify(G2, real behavior) ─► 5 review(auto) ─► 5.5 security? ─► 6 ship ─► 7 learnings(auto)
                            ▲              │ fail               │ findings        │ blocking
                            │              ▼                    ▼                 ▼
                            └─────────── debug (root-cause → fix) ◄────────────────  triggered on any failure
```

- **do uses TDD** (RED→GREEN): failing test first, then minimal code to pass.
- **review runs automatically after verify** (every run, not optional).
- **security is a conditional stage** (5.5): dispatched only when the diff touches auth/input/secrets/OAuth/crypto/public-API surfaces (`trendpulse-security`).
- **debug is a conditional stage**: if verify (G2) fails, or review/security return blocking findings, executor dispatches `debug` to find root cause + fix, then returns to `do` → `verify`. Not a naive retry.
- **ship just confirms the plan is fully executed** (all checkpoints `[x]`, DoD met) and then makes the PR(s).

## How executor dispatches a stage (the contract)

For each stage, use the **Agent tool** to run it in a fresh session. Send a prompt of this shape:

> You are the **`<stage>`** stage of trendpulse-executor for **TASK-NNN**.
> Read and follow `.claude/skills/trendpulse-<stage>/SKILL.md`.
> Task doc: `docs/tasks/task-NNN-slug.md`. Inputs: `<scope / plan / diff / findings as needed>`.
> Do ONLY this stage. Return a structured result:
> `{ status: pass|fail|blocked, summary, findings[]: {severity, where, what, fix}, artifacts[], checkpoint: <id> }`

Recommended `subagent_type` + **model routing** per stage (cheap model for read/mechanical, strong model for reasoning; a *different* model for review than `do` used):

| Stage | subagent_type | model | Why |
|---|---|---|---|
| 1 locate | `Explore` | `haiku` | read-only fan-out search, keeps main context clean |
| 3 do | `general-purpose` | `sonnet`/`opus` | edits files, TDD, runs build |
| 4 verify | `general-purpose` | `sonnet` | Bash: tests, `make logs`, real API requests |
| 5 review | `code-reviewer` (or `python-reviewer`) | `opus` (≠ do's model) | adversarial diff review |
| 5.5 security | `security-reviewer` | `opus` | OWASP-class + project security review (conditional) |
| debug | `general-purpose` | `sonnet`/`opus` | systematic root-cause + fix |
| 6 ship | `general-purpose` | `haiku`/`sonnet` | confirm + git branch/commit/PR |

Pass the chosen model via the Agent tool's `model` option. Executor stays thin: it reads each returned **structured result** (see contract above), **updates the task doc** (tick checkpoint, set `current_step`, append to `## Details`), and decides the next stage. The pipeline is sequential because each stage depends on the previous; only independent sub-checks inside a stage (e.g. verify's static/tests/runtime) run in parallel.

**Stage result contract (validate on return):** every dispatched stage MUST return JSON of shape `{ status: "pass"|"fail"|"blocked"|"skipped", summary: string, findings: [{severity, where, what, fix}], artifacts: [string] }`. If a stage returns malformed output, executor re-dispatches it once with the schema restated, then HALTs.

## State & resume (current_step in the checkpoint)

The task doc's **Checkpoints** block is the operation state and includes `current_step`:

```
## Checkpoints
current_step: 3
baseline_commit: <sha>
branch: ""
lock: ""                 # set to a session/run id while executor is active; prevents two runs on one task
- [x] 1 locate
- [x] 2 plan (G1)
- [ ] 3 do
- [ ] 4 verify (G2, real behavior)
- [ ] 5 review (auto)
- [ ] 5.5 security (if applicable)
- [ ] 6 ship
- [ ] 7 learnings
debug_runs: []
```

On start, executor reads `current_step` and **enters at that stage** — never redoing completed stages. `trendpulse-resume` is a thin entry point that reads `current_step` and starts executor there.

**Lock:** before starting, check `lock`. If it's set and recent, another executor owns this task — refuse (or ask). Otherwise set `lock` to this run's id; clear it on completion/HALT.

## Modes

- **Plan mode (preferred):** a `trendpulse-plan` task doc exists → stages 1–2 already done (`current_step: 3`). Executor begins at `do`.
- **Planless mode:** no task doc → executor dispatches `locate`, creates a stub task doc (frontmatter + Scope + Checkpoints, `current_step: 3`) with a minimal inline plan, then proceeds. Only for small, unambiguous changes.

**No plan → ASK first.** When there is no task doc, executor must NOT silently pick a mode. It asks the user:
> «Плана нет. Сделать план (`trendpulse-plan`) или выполнить без плана (planless)?»
Offer: **(a) Make a plan** — hand off to `trendpulse-plan`, then return and execute it; **(b) Planless** — only for a small, unambiguous change. Recommend (a) when the change is non-trivial, ambiguous, or touches &gt;1 file/consumer.

## Critical rules (enforced on every stage)

- **Surgery, not plowing.** Final diff touches ONLY the declared scope.
- **Read patterns from the codebase, not memory** (codemaps, `docs/CONVENTIONS.md`, neighboring modules) before editing the project source.
- **Build passing ≠ runtime working** — verify enforces real runtime behavior.
- **Manage the environment via `make` (the root `Makefile` — `make up`/`dev-up`/`dev-infra-up`/`down`/`logs`), not raw `docker compose`. Never commit to main.** PR-based workflow.
- **HALT and ask** when: debug fails to resolve after 2 cycles · a new dependency is needed · required config is missing · the diff would exceed scope · an invariant cannot be preserved.
- Communicate in the user's language (Russian).

## Orchestration workflow

<workflow>

  <step n="init" goal="Load state / ask about plan, pick entry stage">
    <action>Find the matching `docs/tasks/task-NNN-*.md`. If found → read its Checkpoints + `current_step` + `baseline_commit` + `lock` + plan, check the `lock` (refuse/ask if another run owns it, else claim it), and enter the pipeline at `current_step` (never redo completed checkpoints).</action>
    <ask>If NO task doc exists → ask the user: «Плана нет. Сделать план (trendpulse-plan) или выполнить без плана?» Do not proceed until answered.</ask>
    <check>If user chooses **plan** → hand off to `trendpulse-plan` (which runs its own discuss/clarify step), then resume executor at `current_step: 3`.</check>
    <check>If user chooses **planless** → dispatch stage 1 (locate); if anything is ambiguous, run a brief discuss (ask focused questions, record answers in the stub doc); then create the stub task doc + minimal plan and set `current_step: 3`.</check>
  </step>

  <step n="1" goal="locate — dispatch the locate agent (if not done)">
    <action>Dispatch `trendpulse-locate` (Explore). Collect scope statement + patterns + blast radius into the task doc.</action>
    <action>Tick checkpoint 1; set `current_step: 2`.</action>
  </step>

  <step n="2" goal="plan — adopt trendpulse-plan output / create inline (G1)">
    <action>Plan mode: adopt the doc's plan. Planless: write a minimal plan (per-file action, DoD, invariants, edge cases, test plan) and shrink it (G1).</action>
    <action>Tick checkpoint 2; set `current_step: 3`.</action>
  </step>

  <step n="3" goal="do — dispatch the implementation agent (TDD)">
    <action>Dispatch a `do` agent with scope + plan + patterns. **TDD (RED→GREEN):** first write the failing test(s) that encode the Acceptance Criteria and confirm they fail; then implement the MINIMAL code to make them pass.</action>
    <action>Hold the hard rules (full type hints — no bare `Any`, no `# type: ignore`; explicit error handling — raise/handle domain errors, never swallow; cross-module via service interfaces; Celery task contracts; settings via pydantic-settings/env, no magic literals; seconds as named constants; pure/immutable pipeline steps; Pydantic at the API boundary). Then self-review `git diff` vs `baseline_commit` and strip accidental changes.</action>
    <action>On return: tick checkpoint 3; set `current_step: 4`.</action>
  </step>

  <step n="4" goal="verify — dispatch the verify agent (G2, real behavior)">
    <action>Dispatch `trendpulse-verify`. It runs tests + lint + typecheck + runtime (`make restart` → `Application startup complete` in `make logs`) AND a **real behavioral check** of the change (e.g. an actual API request against the running endpoint, not just unit tests).</action>
    <check>If `status: fail` → go to debug. If `pass` → tick checkpoint 4; set `current_step: 5`.</check>
  </step>

  <step n="5" goal="review — dispatch the review agent (AUTOMATIC)">
    <action>Always dispatch `trendpulse-review` after verify passes. It adversarially reviews the diff against `docs/CONVENTIONS.md` + codemaps and triages findings by severity.</action>
    <check>If blocking (CRITICAL/HIGH) findings → go to debug/do to fix, then re-verify. If clean → tick checkpoint 5; set `current_step: 5.5`.</check>
  </step>

  <step n="5.5" goal="security — conditional stage">
    <action>If the diff touches auth/authz, OAuth (PKCE/callback/token), input validation, secrets/env, crypto, file upload/S3, public API, or raw SQL/SQLAlchemy text() → dispatch `trendpulse-security`. Otherwise skip (mark checkpoint 5.5 as N/A).</action>
    <check>If blocking findings → debug/do to fix (rotate any exposed secret), then re-verify. If pass/skipped → tick checkpoint 5.5; set `current_step: 6`.</check>
  </step>

  <step n="debug" goal="debug — conditional stage on failure">
    <action>Triggered when verify fails or review returns blocking findings. Dispatch `trendpulse-debug` with the failure evidence. It finds root cause (scientific method, persistent notes), proposes/applies the minimal fix, and records the cycle in the task doc `debug_runs` + `## Details`.</action>
    <action>Return to `do` (apply/confirm fix) → `verify`. HALT and ask the user after 2 unresolved debug cycles.</action>
  </step>

  <step n="6" goal="ship — confirm plan executed, then PR">
    <action>Dispatch `trendpulse-ship`. It first CONFIRMS the plan is fully executed: all checkpoints 1–5 are `[x]`, every Acceptance Criterion and DoD item is satisfied, diff within scope. Only then: branch (`gsd/phase-{N}-{slug}`), Conventional Commit, update task doc (`status: review`, `## Details`), open PR; CI is the final gate.</action>
    <check>If confirmation fails → report the unmet items and return to the relevant stage. If shipped → tick checkpoint 6; set `current_step: 7`.</check>
  </step>

  <step n="7" goal="learnings — automatic, after ship">
    <critical>Runs automatically; not optional. Plans are disposable, lessons are forever.</critical>
    <action>Dispatch (or inline) the learnings step: append a dated block per run to `docs/learnings.md` (Lesson/Why/How-to-apply, Decision/Rationale, Gotcha), mirror per-task decisions into the task `## Details`, and for durable/architectural decisions create `docs/architecture/adr-NNN-*.md` + a `feedback_*`/`project_*` memory (with **Why** + **How to apply**) so the lesson compounds across sessions.</action>
    <action>Tick checkpoint 7; clear `lock`; set `current_step: done`. Summarize the run to the user.</action>
  </step>

</workflow>

## Output

Summarize: stages run (and which were dispatched as agents), what changed, verify evidence (incl. the real behavioral check), review verdict, any debug cycles, PR link, checkpoints/current_step state, and the learning items recorded.
