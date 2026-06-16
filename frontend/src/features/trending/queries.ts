/**
 * React-Query hook for trending — GET /trending?pack=&limit=
 */

import { useQuery } from '@tanstack/react-query';
import { getTrending } from './api';

/** Stable query key prefix for trending. */
export const TRENDING_QUERY_KEY_PREFIX = 'trending' as const;

/** Build the full query key for a pack+limit combo. */
export function trendingQueryKey(pack: string, limit?: number) {
  return [TRENDING_QUERY_KEY_PREFIX, pack, limit] as const;
}

/**
 * useTrending — query hook for GET /trending?pack=
 *
 * Enabled only when `pack` is non-empty. The response includes
 * `warming_up=true` when the showcase tenant is not yet warmed;
 * consumers should render the "Collecting signals…" placeholder in that case.
 *
 * staleTime: 30s — trending is live data but doesn't need to refresh every render.
 *
 * Auto-refresh while warming up: on first visit the showcase tenant may still be
 * warming (`warming_up=true`, empty items). Instead of forcing the user to reload
 * the page, poll every `WARMUP_POLL_MS` until real data arrives, then stop. This
 * fixes "selected a pack but nothing showed until I refreshed twice".
 */
const WARMUP_POLL_MS = 4_000;

export function useTrending(pack: string, limit?: number) {
  return useQuery({
    queryKey: trendingQueryKey(pack, limit),
    queryFn: () => getTrending(pack, limit),
    enabled: pack.length > 0,
    staleTime: 30_000,
    // Poll only while the backend reports it is still warming up; stop once data lands.
    refetchInterval: (query) =>
      query.state.data?.warming_up ? WARMUP_POLL_MS : false,
  });
}
