---
id: TASK-095
title: Watchlists «Signal Desk» redesign — dense sortable signal table (frontend)
status: done
owner: frontend
created: 2026-06-14
branch: task/095-watchlists-signal-desk
tags: [frontend, ui, watchlists, design-port, visual-only]
---

# TASK-095 — Watchlists «Signal Desk» redesign

## Goal

Redesign the React watchlists screen (`/watchlists`) to match the approved
"Signal Desk" mockup
(`designs/trendPulse/landing/watchlists-variant-a.html`): a dense, sortable
signal-table layout in the Aurora `.fs-*` dark design language. **Visual /
structural only** — all data fetching, mutations, validation, routes, query
keys and plan-gating stay byte-for-byte identical.

## Scope (touch-only)

- `frontend/src/pages/watchlists/list.tsx` — page: toolbar (search + status
  segment + density toggle), Signal Desk table, empty/first-run state, plan
  upsell. Same hooks/handlers as before.
- `frontend/src/features/watchlists/signal-desk.ts` — **new**, pure helpers
  (filter / sort / threshold-bar percent / status derivation). Unit-tested.
- `frontend/src/features/watchlists/watchlist-row.tsx` — **new**, one table row
  (name+topic, sparkline placeholder, velocity placeholder, sources, threshold
  mini-bar, last-alert, status, hover/focus quick actions: view / edit / delete).
- `frontend/src/features/watchlists/watchlists-toolbar.tsx` — **new**, presentational
  toolbar (search input, status segment, density toggle) driven by local UI state.
- `frontend/src/features/watchlists/index.ts` — export the new pieces.
- `frontend/src/app/app.css` — add Signal Desk `.desk-*` / `.wl-name` / `.spark` /
  `.vel-badge` / `.thr` / `.row-actions` / `.icon-btn` / `.cell-*` / `.starter` /
  `.section-label` / `.legend` / `.status-dot` rules using existing `--fs-*` tokens.
- `frontend/tests/unit/watchlists/signal-desk.spec.ts` — **new** unit tests.
- `docs/tasks/task-095-*.md` + `docs/tasks/tasks-index.md` — this doc + index row.

## Real-data mapping vs mockup

Backend `WatchlistRead` only provides: `id`, `topic`, `channel.handle`,
`alert_config.{score_threshold, min_channels, notification_lang}`. A watchlist =
exactly one channel (ADR-001).

| Mockup element        | Backed by real data?                                    |
|-----------------------|---------------------------------------------------------|
| Name + topic          | YES — `channel.handle` + `topic`                        |
| Threshold mini-bar    | YES — `alert_config.score_threshold` (0–100 → width %)  |
| Sources count         | YES — 1 channel per watchlist (ADR-001)                 |
| Status                | NO pause/live field → all render neutral "Active"       |
| 24h sparkline series  | NO → neutral muted placeholder, accessible "—" label    |
| Live "×baseline"      | NO → neutral placeholder ("—"), no fake numbers         |
| Last alert            | NO field → neutral "—"                                  |
| Pause action          | NO backend endpoint → omitted (no fabricated API call)  |
| Free-plan upsell      | YES — `useCurrentUser().plan` + `PLAN_MAX_WATCHLISTS`   |

Decorative signal elements with no backend source degrade gracefully (neutral
placeholder), per the no-fake-data invariant.

## Acceptance Criteria

- [ ] Layout matches `watchlists-variant-a.html` (dense sortable table, toolbar,
      empty/first-run, upsell) within real-data constraints above.
- [ ] All CRUD / plan-gating / pause-less edit-delete / routes / query keys /
      mutations identical — behaviour & data preserved.
- [ ] `npm run build`, `npm run lint`, `npm run test:unit` all green.
- [ ] Browser screenshot of the rendered screen captured.
- [ ] Content verbatim; brand Foresignal; 0 user-facing "TrendPulse".

## Invariants

- VISUAL ONLY: no edits to data fetching, mutations, validation, routes,
  SITE_ROUTES, plan-gating, query keys. Sort/filter/density are client-side UI
  state, kept local to the page.
- Touch only `frontend/` + this doc + `tasks-index.md`. Never touch
  `ops/ansible/vault/*`.

## Checkpoints

- 2026-06-14 — locate+plan done; data model audited (real fields enumerated);
  task doc + index row created. Implementing.
- 2026-06-14 — done. Signal Desk implemented (toolbar, sortable table, row
  quick-actions, density toggle, empty/first-run, plan upsell). G2 green:
  `npm run build` ✓, `npm run lint` ✓, `npm run test:unit` ✓ (273 passed, +18
  new signal-desk helper tests). Screenshots `/tmp/watchlists-signal-desk.png`
  (desktop) + `/tmp/watchlists-signal-desk-mobile.png`. Visual-only invariant
  held: queries/api/model/router untouched; sparkline/velocity/last-alert/pause
  degraded to neutral placeholders (no fake data, no fabricated API).
