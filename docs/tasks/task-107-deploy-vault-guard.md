---
id: TASK-107
title: Deploy vault-guard preflight — block make deploy on divergent/uncommitted vault
status: in-progress
owner: infra
created: 2026-06-15
updated: 2026-06-15
baseline_commit: "4a7c1d6"
branch: "task/107-deploy-vault-guard"
tags: [reliability, deploy, ansible, vault, safety, incident-prevention]
---

# TASK-107 — Deploy vault-guard preflight

> Directly prevents the 2026-06-15 incident (`cache/INCIDENT-2026-06-15-deploy-authkey.md`):
> `make deploy` from one worktree (committed vault) overwrote prod's live TG sessions, which were
> running ANOTHER worktree's UNCOMMITTED vault → AuthKeyDuplicated → ingest down. Root: the vault
> had no single source of truth across worktrees, and nothing blocked deploying a divergent one.

## Goal
A preflight that runs before the ansible deploy and ABORTS if any git worktree (the deploying one
OR any sibling) has UNCOMMITTED changes to `ops/ansible/vault/sensitive.vault.yml`. That is exactly
the condition under which the live-prod vault may differ from what you're about to deploy. Escape
hatch `SKIP_VAULT_GUARD=1` for when the owner has manually reconciled (loud warning).

## Discussion
- Q: What's the minimal check that would have CAUGHT this incident? → A: "a sibling worktree has
  uncommitted vault edits." At incident time, `apps/trendPulse` (main) had a ~233-line uncommitted
  `sensitive.vault.yml`; I deployed the committed vault from `apps/trendPulse-reliability`. Blocking
  on "ANY worktree has uncommitted vault changes" stops exactly that.
- Q: Also check vault vs live prod? → A: out of scope (would require decrypting + querying prod
  secrets). The uncommitted-vault check is the high-signal, implementable guard; reconciling to one
  committed vault is the discipline it enforces.
- Q: Python vs bash? → A: Python (testable pure core, no-Any, matches the stack); stdlib-only
  (`subprocess`), no new deps; runnable as `make vault-guard`.
- Q: Override? → A: `SKIP_VAULT_GUARD=1` — prints a loud warning and proceeds (emergencies / owner
  has reconciled). Default = enforce.

## Scope
- `release/scripts/vault_guard.py` — pure `parse_worktrees`/`dirty_vault_worktrees` + `main()`.
- `Makefile` — `vault-guard:` target + call it as the first step of `deploy:` (after the inventory
  check, before ansible); honor `SKIP_VAULT_GUARD`.
- `backend/tests/unit/test_vault_guard.py` — unit-test the pure functions (importlib-loaded).

Touch ONLY the above. Do NOT touch: the ansible playbook, vault contents, app code.
Blast radius: the `make deploy` preflight only. No runtime/app behavior.

## Acceptance Criteria
- [ ] **AC1 — detect dirty vault.** `dirty_vault_worktrees` returns the worktrees whose vault status
  is non-empty (uncommitted/staged/untracked changes to the vault file).
- [ ] **AC2 — parse worktrees.** `parse_worktrees` extracts paths from `git worktree list --porcelain`.
- [ ] **AC3 — deploy blocked.** `make deploy` aborts (non-zero, clear message naming the dirty
  worktree(s) + remediation) when any worktree has an uncommitted vault; proceeds when all clean.
- [ ] **AC4 — override.** `SKIP_VAULT_GUARD=1 make deploy` warns and proceeds.
- [ ] **AC5 — green.** `make ci-fast` green; script is mypy/ruff clean.

## Plan
1. (RED) test the pure functions (parse + dirty detection) with fixture git outputs.
2. (GREEN) write `vault_guard.py`; add Makefile `vault-guard` target + wire into `deploy`.
3. verify (`make ci-fast` + run `make vault-guard` locally); review.

## Invariants
- Guard is fail-CLOSED on the incident condition (uncommitted vault anywhere) unless explicitly skipped.
- Pure functions have no side effects; only `main()` runs git / exits.
- Never reads or prints vault CONTENTS (only file paths + status flags).

## Edge cases
- Single worktree, clean vault → pass. Dirty vault in current worktree → block. Dirty in sibling → block.
- `git worktree list` with one entry → still works. Vault file absent/clean → empty status → pass.

## Test plan
- Unit (`test_vault_guard.py`): parse_worktrees over sample porcelain; dirty_vault_worktrees with a
  fake status_fn (clean → []; one dirty → [that wt]; multiple). `make ci-fast` green.
- Manual: `make vault-guard` in a clean tree → OK exit 0; touch the vault → blocks.

## Review (inline adversarial) + LIVE proof
Pure helpers unit-tested; `main()` is a thin git/exit wrapper. **Proven live:** run on the current
machine the guard BLOCKED (exit 1), correctly naming `apps/trendPulse` as having an uncommitted
vault — i.e. it would have prevented the 2026-06-15 deploy. `SKIP_VAULT_GUARD=1` → exit 0 (warn).
Never prints vault contents (only paths + a dirty flag) → security skip justified. Fail-closed on
the incident condition. NOTE: deploys stay BLOCKED until `apps/trendPulse`'s uncommitted vault is
committed/reconciled (or SKIP used) — that is the intended forcing function.

## Checkpoints
current_step: 6
baseline_commit: "4a7c1d6"
branch: "task/107-deploy-vault-guard"
lock: "reliability-loop"
- [x] 1 locate (Makefile deploy target + incident root cause + worktree layout)
- [x] 2 plan (G1 — minimal)
- [x] 3 do (script + Makefile wire + 6 unit tests)
- [x] 4 verify (G2 — 980 unit, mypy/ruff clean, guard proven live block+override)
- [x] 5 review (inline adversarial — live-proven, pure helpers tested)
- [x] 5.5 security (skip — never reads/prints vault contents, only paths + status)
- [x] 6 ship (PR)
- [ ] 7 learnings (auto)
