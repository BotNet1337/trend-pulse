"""TASK-107 — unit tests for the deploy vault-guard pure helpers.

The script lives in release/scripts (outside backend/src), so it is importlib-loaded here (same
pattern as the eval harness). Only the pure functions are tested; main() shells out to git.
"""

from __future__ import annotations

import importlib.util as ilu
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "release" / "scripts" / "vault_guard.py"
_spec = ilu.spec_from_file_location("vault_guard", _SCRIPT)
assert _spec is not None and _spec.loader is not None
vg = ilu.module_from_spec(_spec)
_spec.loader.exec_module(vg)


def test_parse_worktrees_extracts_paths() -> None:
    porcelain = (
        "worktree /repo/main\nHEAD abc123\nbranch refs/heads/main\n\n"
        "worktree /repo/feature-wt\nHEAD def456\nbranch refs/heads/feat\n\n"
        "worktree /repo/detached\nHEAD 789aaa\ndetached\n"
    )
    assert vg.parse_worktrees(porcelain) == ["/repo/main", "/repo/feature-wt", "/repo/detached"]


def test_parse_worktrees_empty() -> None:
    assert vg.parse_worktrees("") == []


def test_dirty_vault_worktrees_all_clean() -> None:
    assert vg.dirty_vault_worktrees(["/a", "/b"], lambda _wt: "") == []


def test_dirty_vault_worktrees_one_dirty() -> None:
    status = {"/a": "", "/b": " M ops/ansible/vault/sensitive.vault.yml\n"}
    assert vg.dirty_vault_worktrees(["/a", "/b"], lambda wt: status[wt]) == ["/b"]


def test_dirty_vault_worktrees_multiple_dirty() -> None:
    status = {"/a": "?? sensitive.vault.yml", "/b": "  ", "/c": "M  sensitive.vault.yml"}
    assert vg.dirty_vault_worktrees(["/a", "/b", "/c"], lambda wt: status[wt]) == ["/a", "/c"]


def test_vault_rel_path_is_the_committed_vault() -> None:
    assert vg.VAULT_REL_PATH == "ops/ansible/vault/sensitive.vault.yml"
