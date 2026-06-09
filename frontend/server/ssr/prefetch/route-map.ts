/**
 * SSR prefetch route-map for TrendPulse.
 *
 * Maps URL patterns (TanStack Router `$param` syntax) to fetcher compositions.
 * More specific patterns must appear BEFORE less specific ones — the matcher
 * returns the first match.
 *
 * Auth pages (anon layout) are empty — they have no server-prefetched data.
 * Protected pages prefetch current_user + relevant entity data so that
 * AuthGuard, page headers, and list views render in the first SSR pass without
 * the client needing to re-fetch on mount.
 */
import type { Fetcher } from './types';
import { fetchCurrentUser, fetchWatchlists } from './fetchers';

// ─── Patterns (most-specific first) ─────────────────────────────────────────

export const PREFETCH_ROUTE_PATTERNS: readonly string[] = [
  // Protected routes — prefetch current_user + entity data
  '/watchlists/new',
  '/watchlists/$watchlistId',
  '/watchlists',
  '/alerts/$alertId',
  '/alerts',
  '/account/settings',
  '/billing',
  // Root / redirects to /watchlists — prefetch current_user only
  '/',
];

// ─── Fetcher compositions ─────────────────────────────────────────────────

export const PREFETCH_ROUTES: Record<string, Fetcher[]> = {
  // Watchlist list — current_user (for auth guard + header) + watchlist data
  '/watchlists': [fetchCurrentUser, fetchWatchlists],

  // Watchlist detail / create — current_user only (detail fetches individually)
  '/watchlists/$watchlistId': [fetchCurrentUser],
  '/watchlists/new': [fetchCurrentUser],

  // Alerts — current_user only (entity-specific fetch happens client-side)
  '/alerts': [fetchCurrentUser],
  '/alerts/$alertId': [fetchCurrentUser],

  // Account / billing — current_user only
  '/account/settings': [fetchCurrentUser],
  '/billing': [fetchCurrentUser],

  // Root / — current_user (guard check before redirect to /watchlists)
  '/': [fetchCurrentUser],
};

// No param aliases needed — the route params are passed as-is.
export const PARAM_ALIASES: Record<string, string> = {};
