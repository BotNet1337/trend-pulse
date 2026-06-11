/**
 * TASK-067: shared (server + client) shape of one proof-of-speed case.
 * Mirrors backend `CaseItem` (backend/src/api/cases/schemas.py) — aggregate
 * fields only, title is sanitized server-side.
 *
 * Type-only module: imported by SSR server code and React sections alike,
 * must stay free of runtime dependencies.
 */
export interface CaseItem {
  title: string;
  viral_score: number;
  /** UTC ISO timestamp when the cluster was first detected. */
  first_seen: string;
  /** UTC ISO timestamp when the topic hit mainstream media (always present). */
  mainstream_at: string;
  lead_time_seconds: number;
  /** MVP = 1 — deliberately NOT rendered on the landing (see TASK-067 Discussion). */
  channels_count: number;
}
