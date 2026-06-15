---
id: TASK-104
title: Index posts.fetched_at so ingest-staleness MAX() is an index scan, not a seqscan
status: backlog
owner: backend
created: 2026-06-15
updated: 2026-06-15
tags: [reliability, performance, postgres, index, observability]
---

# TASK-104 — `ix_posts_fetched_at` (backlog)

> Spun off from TASK-100 review (MEDIUM). The ingest-staleness check runs
> `SELECT EXTRACT(EPOCH FROM (NOW() - MAX(fetched_at))) FROM posts` every 300s.
> `posts.fetched_at` is unindexed, so `MAX` is a sequential scan over the `posts`
> table — cheap now (~58k rows) but grows linearly (the retention sweep NULLs text
> but keeps rows; audit's "Postgres rows grow" finding). When the table grows large,
> add a descending btree index so Postgres serves `MAX(fetched_at)` via a backward
> index scan.

## Plan (when scheduled)
1. Alembic migration: `CREATE INDEX ix_posts_fetched_at ON posts (fetched_at DESC);`
   (consider `CONCURRENTLY` — needs a non-transactional migration; mind the project's
   migration drop-list / compose-CI gotchas).
2. Confirm the staleness query plan flips to an index scan (`EXPLAIN`).
3. No code change — the existing query benefits automatically.

## Trigger
Schedule when `posts` row count is large enough that the 300s `MAX(fetched_at)` seqscan
shows up in DB latency, or proactively before a long unattended run with high ingest volume.
