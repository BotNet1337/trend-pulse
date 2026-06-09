/**
 * SSR prefetch fetchers for TrendPulse.
 *
 * Cookie-forward auth: each fetcher receives a per-request axios instance
 * that carries the inbound `Cookie` header (containing `fastapiusersauth`).
 * No Bearer tokens are used — TrendPulse backend authenticates via httpOnly
 * cookie only.
 *
 * Query keys MUST match the runtime keys used by client hooks:
 *   - `CURRENT_USER_QUERY_KEY` = `['viewer', 'me']`  (entities/viewer/model.ts)
 *   - `WATCHLISTS_QUERY_KEY`   = `['watchlists', 'list']`  (entities/watchlist/model.ts)
 *
 * A mismatch makes hydration a no-op (hook refetches silently on mount).
 */
import type { Fetcher } from './types';
import type { CurrentUser } from '../../../src/entities/viewer/model';
import type { WatchlistRead } from '../../../src/entities/watchlist/model';

// ─── Current user ──────────────────────────────────────────────────────────

/**
 * Fetch the current authenticated user from GET /users/me.
 *
 * Returns a `SerializedQuery` with key `['viewer', 'me']` on success.
 * Returns `null` on 401 (the runner treats any 401 as "drop hydration").
 *
 * The prefetch runner's 401-detection happens via `isUnauthorized(result.reason)` —
 * axios throws on non-2xx (validateStatus enforces this), so a 401 becomes a
 * rejected promise, not a null return. `fetchCurrentUser` itself never needs to
 * handle 401 explicitly — it will propagate naturally.
 */
export const fetchCurrentUser: Fetcher = async ({ api }) => {
  const response = await api.get<CurrentUser>('/users/me');
  return {
    // Must match CURRENT_USER_QUERY_KEY in src/entities/viewer/model.ts
    key: ['viewer', 'me'] as const,
    data: response.data,
  };
};

// ─── Watchlists ────────────────────────────────────────────────────────────

/**
 * Fetch the current user's watchlists from GET /watchlists.
 *
 * Returns a `SerializedQuery` with key `['watchlists', 'list']` on success.
 * 401 propagates and triggers the runner's drop-hydration logic.
 */
export const fetchWatchlists: Fetcher = async ({ api }) => {
  const response = await api.get<WatchlistRead[]>('/watchlists');
  return {
    // Must match WATCHLISTS_QUERY_KEY in src/entities/watchlist/model.ts
    key: ['watchlists', 'list'] as const,
    data: response.data,
  };
};
