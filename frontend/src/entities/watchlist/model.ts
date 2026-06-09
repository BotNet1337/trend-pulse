/**
 * Watchlist entity model — types derived from OpenAPI gen.types (C1 invariant).
 * Source of truth: backend schema WatchlistRead / WatchlistCreate / WatchlistUpdate.
 * Do NOT redeclare shapes manually; use the generated types.
 */

import type { components } from '@/shared/api/gen.types';

/** A persisted watchlist row (one channel + topic + alert_config). */
export type WatchlistRead = components['schemas']['WatchlistRead'];

/** Create payload for POST /watchlists. */
export type WatchlistCreate = components['schemas']['WatchlistCreate'];

/** Partial update payload for PATCH /watchlists/{id}. */
export type WatchlistUpdate = components['schemas']['WatchlistUpdate'];

/** Channel reference — handle + kind (currently only telegram). */
export type ChannelRef = components['schemas']['ChannelRef'];

/** Alert configuration for a watchlist. */
export type AlertConfig = components['schemas']['AlertConfig'];

/** Source platform kind. */
export type SourceKind = components['schemas']['SourceKind'];

/** Stable query key for the watchlist list. */
export const WATCHLISTS_QUERY_KEY = ['watchlists', 'list'] as const;

/** Stable query key factory for a single watchlist. */
export const watchlistQueryKey = (id: number) => ['watchlists', 'detail', id] as const;
