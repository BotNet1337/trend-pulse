/**
 * SSR prefetch fetchers for TrendPulse.
 *
 * C1 (foundation): no prefetch needed — auth pages are anonymous,
 * account settings loads client-side. Watchlists prefetch lands in C3.
 *
 * Stubs kept so the module exports are stable; downstream imports from
 * route-map / run compile without errors.
 */
import type { Fetcher } from './types';

// No-op fetcher placeholder — returns null (nothing to hydrate). Real named
// TrendPulse fetchers (watchlists) are introduced in C3 (task-015).
export const fetchPlaceholder: Fetcher = async () => null;
