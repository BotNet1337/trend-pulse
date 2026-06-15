#!/usr/bin/env python3
"""Deploy vault-guard preflight (TASK-107).

Blocks `make deploy` when ANY git worktree (the deploying one or a sibling) has UNCOMMITTED
changes to the Ansible vault — the exact condition that caused the 2026-06-15 incident, where a
deploy from one worktree (committed vault) overwrote prod's live TG sessions running another
worktree's uncommitted vault → AuthKeyDuplicated → ingest down.

Pure helpers (`parse_worktrees`, `dirty_vault_worktrees`) are unit-tested; only `main()` shells out
to git and exits. Never reads or prints vault CONTENTS — only worktree paths + a dirty flag.

Escape hatch: `SKIP_VAULT_GUARD=1` warns and exits 0 (only after manually reconciling the vault).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

# Vault path relative to each worktree root (same in every worktree of this repo).
VAULT_REL_PATH = "ops/ansible/vault/sensitive.vault.yml"
_SKIP_ENV = "SKIP_VAULT_GUARD"


def parse_worktrees(worktree_list_porcelain: str) -> list[str]:
    """Extract worktree root paths from `git worktree list --porcelain` output.

    The porcelain format emits one ``worktree <path>`` line per worktree (plus HEAD/branch lines).
    """
    paths: list[str] = []
    for line in worktree_list_porcelain.splitlines():
        if line.startswith("worktree "):
            paths.append(line[len("worktree ") :].strip())
    return paths


def dirty_vault_worktrees(
    worktree_paths: list[str],
    vault_status: Callable[[str], str],
) -> list[str]:
    """Return the worktrees whose vault file has uncommitted changes.

    ``vault_status(path)`` returns the ``git status --porcelain`` output for the vault file in that
    worktree — a non-empty result means modified/staged/untracked (i.e. divergent from committed).
    """
    return [path for path in worktree_paths if vault_status(path).strip()]


def _git(args: list[str]) -> str:
    # Fixed `git` argv, no shell, no user input — safe subprocess call.
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def main() -> int:
    if os.environ.get(_SKIP_ENV):
        print(
            f"[vault-guard] {_SKIP_ENV} set — SKIPPING the vault divergence check. "
            "Ensure the deployed vault matches what live prod is running.",
            file=sys.stderr,
        )
        return 0

    worktrees = parse_worktrees(_git(["worktree", "list", "--porcelain"]))
    dirty = dirty_vault_worktrees(
        worktrees,
        lambda wt: _git(["-C", wt, "status", "--porcelain", "--", VAULT_REL_PATH]),
    )
    if dirty:
        print(
            "[vault-guard] BLOCKED: uncommitted changes to "
            f"{VAULT_REL_PATH} in:\n  - " + "\n  - ".join(dirty) + "\n"
            "Deploying now could SWAP prod's live TG sessions and trigger AuthKeyDuplicated "
            "(see cache/INCIDENT-2026-06-15-deploy-authkey.md). Reconcile the vault to a single "
            f"committed source of truth across worktrees first, or set {_SKIP_ENV}=1 to override "
            "if you have manually verified the vault matches live prod.",
            file=sys.stderr,
        )
        return 1

    print("[vault-guard] OK — no uncommitted vault changes in any worktree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
