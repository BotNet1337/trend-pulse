/**
 * SSR prefetch route-map for TrendPulse.
 *
 * C1 (foundation): empty — no server-side hydration in the initial scaffold.
 * Watchlists prefetch + route-map entries land in C3.
 */
import type { Fetcher } from './types';

// No routes require SSR hydration in C1.
export const PREFETCH_ROUTE_PATTERNS: readonly string[] = [];

export const PREFETCH_ROUTES: Record<string, Fetcher[]> = {};

// No param aliases needed until C3 routes land.
export const PARAM_ALIASES: Record<string, string> = {};
