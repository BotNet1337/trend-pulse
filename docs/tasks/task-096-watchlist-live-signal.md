---
id: TASK-096
title: Real live-signal per watchlist — velocity / sparkline / last-alert
status: in-progress
owner: backend
created: 2026-06-15
branch: task/096-watchlist-live-signal
tags: [backend, frontend, watchlists, signal, aggregation]
---

# TASK-096 — Real live-signal per watchlist

## Goal

The redesigned `/watchlists` "Signal Desk" screen (TASK-095) renders per-row
signal slots that currently show "— no live data" placeholders because the
backend never exposed them. Make each watchlist return its **live signal** and
wire the frontend rows to it:

- `live_velocity` — the scorer's normalized `velocity` component (∈ [0, 1]) of
  the latest in-window `Score` for the watchlist.
- `live_score` — the latest `viral_score` for the watchlist.
- `sparkline_24h` — hourly series (array of numbers, max `viral_score` per hour
  over the last 24h) for the row's mini-chart.
- `last_alert_at` — `first_seen` of the most recent alert for the watchlist
  (nullable).

All fields are nullable / empty-array when there is genuinely no data (graceful)
— never fabricated.

## Scope (touch-only)

- `backend/src/storage/repositories/signal_repo.py` — **new**, the per-watchlist
  signal aggregation (grouped queries keyed by `channel_id`, no N+1).
- `backend/src/api/watchlist/schemas.py` — add `WatchlistSignal` nested model and
  a `signal` field on `WatchlistRead`.
- `backend/src/api/watchlist/service.py` — populate `signal` in `list_for_user`
  (and `get`) via one batched aggregation per request.
- `backend/tests/integration/test_watchlist_signal.py` — **new** integration test.
- `frontend/src/features/watchlists/signal-desk.ts` — pure helpers: velocity
  badge tier (hot/warm/calm) + sparkline points builder.
- `frontend/src/features/watchlists/watchlist-row.tsx` — render real sparkline,
  velocity ×baseline badge and last-alert from the new `signal` field.
- `frontend/tests/unit/watchlists/signal-desk.spec.ts` — extend unit tests.
- regenerated `frontend/src/shared/api/openapi.json` + `gen.types.ts`.
- `docs/tasks/task-096-watchlist-live-signal.md` (+ index row).

## Acceptance Criteria

1. `GET /watchlists` rows carry a nested `signal` object with `live_velocity`,
   `live_score`, `sparkline_24h`, `last_alert_at`.
2. Aggregation is correct: `live_velocity` / `live_score` = the latest in-window
   `Score` values for the watchlist's channel; `sparkline_24h` = max `viral_score`
   per hour over the last 24h; `last_alert_at` = the most recent alert's
   `first_seen`.
3. Cross-user data and clusters with no in-window post on the watchlist's channel
   are EXCLUDED. No data → nulls / empty array (graceful, never fabricated).
4. The aggregation uses one / few grouped queries for the whole list — no N+1.
5. Frontend rows render the real sparkline, the velocity ×baseline badge (with
   hot/warm/calm tiers) and `last_alert_at`; graceful empty state preserved.
6. OpenAPI artifacts regenerated and committed (openapi-drift-check passes).
7. Existing watchlist CRUD / plan-gating / alert logic / routes / query-keys
   unchanged; backend + frontend test suites green.

## Discussion

### Topic-join decision — CHANNEL OVERLAP, not topic-string equality

The task brief's data-model note assumed `Cluster.topic == Watchlist.topic`. That
is **wrong for this system** and is exactly the prod bug TASK-084 fixed.
`scorer/tasks.py` documents (and the live system relies on) the fact that
`Cluster.topic` is FREE TEXT (the first post's `text[:255]`, e.g. «Паоло
Ардоино: …») while `Watchlist.topic` is a CATEGORY label (e.g. "crypto"). They
can NEVER be equal, so a topic-equality join would always return nothing — the
same root cause that left prod with 9,400+ clusters and 0 scores.

The scorer links a cluster to a watched topic by **channel overlap**: a cluster
matches a watchlist when the cluster has at least one in-window `Post` on the
watchlist's `channel_id`. The signal aggregation MUST use the same join to be
consistent with the scorer. So:

> A watchlist's signal = aggregate over the `Score` / `Alert` rows of clusters
> that have ≥1 in-window `Post` on the watchlist's `channel_id`, scoped to the
> watchlist's `user_id`.

The linkage path is `Watchlist.channel_id` → `Post.channel_id` (+ `Post.user_id`,
`Post.posted_at >= now − 24h`) → distinct `Post.cluster_id` → `Score` / `Alert`
of those clusters. A cluster whose posts span several watched channels attributes
its score to each of those channels (mirrors the scorer's per-cluster signal; the
"best-overlap → one Score per cluster" rule is a scorer-write concern, the desk is
a read view). Window = 24h (matches the sparkline window and the product's "Live
signal (24h)" column header; named constant `_SIGNAL_WINDOW_SECONDS`).

### Endpoint-shape decision — extend the list response

Chosen: extend the existing `GET /watchlists` list response with a nested
`signal` object rather than adding `GET /watchlists/signals`. The frontend gets
the signal in the SAME call it already makes for the table (fewer round-trips,
no new query key, no extra cache to invalidate). The aggregation is done with a
few grouped queries keyed by `channel_id` for the whole list (built once per
request, then mapped onto each row), so extending the list does NOT introduce an
N+1 — it adds three constant-count grouped queries regardless of list size.

### live_velocity semantics

`live_velocity` is the scorer's `Score.velocity` component verbatim (∈ [0, 1],
the bounded cross-channel burst term). The frontend renders it as a "×baseline"
style badge with hot/warm/calm tiers (thresholds chosen in `signal-desk.ts`:
`hot ≥ 0.5`, `warm ≥ 0.2`, else `calm`) — a presentation choice, the number is
the real normalized velocity, never invented.

### sparkline source

`scores` is upserted (one row per `(user_id, cluster_id)`, `computed_at` updated
in place), so the hourly series is built from the in-window `Score.computed_at`
truncated to the hour, taking `max(viral_score)` per hour bucket across the
watchlist's clusters. With dense data this yields up to 24 buckets; sparse data
yields fewer (graceful). This is the best hourly series the persisted model
supports without a new history table (out of scope).

## Invariants

- INV1: tenant isolation — every signal query filters `user_id`; another tenant's
  scores/alerts can never leak into a watchlist's signal.
- INV2: graceful — no data ⇒ `live_velocity=None`, `live_score=None`,
  `sparkline_24h=[]`, `last_alert_at=None`. Never fabricate.
- INV3: no N+1 — signal for the whole list is built from a fixed number of
  grouped queries, independent of list length.
- INV4: read-only — the signal aggregation never writes; CRUD / scorer / alert
  write paths are untouched.
- INV5: immutability / pure-read — the repo returns plain DTOs, mutates nothing.

## Checkpoints

- [x] locate — read models, scorer (TASK-084 channel-overlap join), repo/API/test
  conventions, frontend row + signal-desk.
- [x] plan — decisions recorded above.
- [x] do — backend repo + schema + service + integration test; frontend wiring +
  unit tests.
- [x] verify (G2) — backend pytest GREEN (939 unit + 22 watchlist/signal/scorer
  integration + 32 alerts/packs on disposable pgvector :15433), ruff/mypy clean;
  frontend build + lint + 286 unit tests GREEN; openapi regenerated (artifacts
  committed → drift-check passes against HEAD).
- [x] ship — commit, push, PR.
