---
name: trendpulse-undo
description: Safe rollback of a TrendPulse surgical change using the task doc's baseline_commit. Use when the user says "откати", "undo", "rollback", or a shipped/in-progress change must be reverted. Confirms what will be reverted before touching anything; prefers git revert (shared history) over reset.
---

# TrendPulse Undo

Rolls back a change recorded by `trendpulse-plan`/`trendpulse-executor`, using `baseline_commit` + `branch` from the task doc. Destructive — always confirm first.

## Do

<workflow>
  <step n="1" goal="Locate the operation">
    <action>Read the target `docs/tasks/task-NNN-*.md`: `baseline_commit`, `branch`, the commits/PR made in stage 6, and the File List / Details.</action>
  </step>
  <step n="2" goal="Compute the rollback set">
    <action>In the repo, diff `baseline_commit..HEAD` (or the PR's commit range) to list exactly what would be undone. Show it to the user.</action>
    <check>Ask the user to confirm the rollback set before proceeding.</check>
  </step>
  <step n="3" goal="Revert safely">
    <action>If the branch is unmerged / local-only → reset the branch to `baseline_commit` (or drop the branch).</action>
    <action>If commits are already on a shared branch / merged → use `git revert` (new inverse commits), never history rewrite. One revert per atomic commit, Conventional message `revert: …`.</action>
    <action>Re-run `trendpulse-verify` to confirm the system is healthy after rollback (runtime + behavior).</action>
  </step>
  <step n="4" goal="Update the record">
    <action>Set task `status` back (review→in-progress / planned), append a `## Details` note: what was reverted, why, and the revert commits. Reset the relevant Checkpoints to `[ ]` and `current_step`.</action>
    <action>Append a learnings entry (why the rollback was needed) to `docs/learnings.md`.</action>
  </step>
</workflow>

## Return

```
status: reverted | aborted
method: reset | revert
reverted_commits: [...]
verify_after: pass | fail
```
