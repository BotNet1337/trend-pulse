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

// No-op fetcher placeholder — returns null (nothing to hydrate).
export const fetchPlaceholder: Fetcher = async () => null;

// Re-exports to keep the public API shape stable for future C3 additions.
export {
  fetchPlaceholder as fetchWorkspacesList,
  fetchPlaceholder as fetchWorkspaceById,
  fetchPlaceholder as fetchChannelsList,
  fetchPlaceholder as fetchPostsList,
  fetchPlaceholder as fetchPostById,
  fetchPlaceholder as fetchCalendarPosts,
  fetchPlaceholder as fetchDashboard,
  fetchPlaceholder as fetchModerationQueue,
  fetchPlaceholder as fetchWorkspacePublications,
};
