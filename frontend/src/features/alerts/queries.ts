/**
 * React-Query hooks for alerts — list (with pagination/"load more") + detail.
 * Types from gen.types (C1 invariant).
 */

import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { listAlerts, getAlert } from './api';
import { ALERTS_QUERY_KEY, alertQueryKey } from '@/entities/alert/model';

// Default page size for the feed — matches backend DEFAULT_ALERTS_PAGE_SIZE.
const ALERTS_PAGE_SIZE = 20;

// ─── useAlerts — infinite / "load more" pagination ───────────────────────────

/**
 * Paginated alerts feed.
 *
 * Uses `useInfiniteQuery` so the UI can show "Load more" or infinite scroll.
 * The first page is fetched immediately; subsequent pages are fetched on demand.
 *
 * `history_unavailable` is surfaced from the first page response so the UI
 * can render the plan-upgrade upsell without inspecting individual pages.
 */
export function useAlerts() {
  return useInfiniteQuery({
    queryKey: ALERTS_QUERY_KEY,
    queryFn: ({ pageParam = 0 }) =>
      listAlerts({ limit: ALERTS_PAGE_SIZE, offset: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const { offset, limit, total } = lastPage;
      const nextOffset = offset + limit;
      return nextOffset < total ? nextOffset : undefined;
    },
    staleTime: 30_000,
  });
}

// ─── useAlert — single alert detail ──────────────────────────────────────────

/** Get a single alert by id. Throws on 404 (caught by the page). */
export function useAlert(id: number) {
  return useQuery({
    queryKey: alertQueryKey(id),
    queryFn: () => getAlert(id),
    enabled: !Number.isNaN(id),
    staleTime: 30_000,
    retry: (failureCount, error) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 404) return false;
      return failureCount < 2;
    },
  });
}
