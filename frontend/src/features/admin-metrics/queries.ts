/**
 * React-Query hooks for the admin money dashboard (TASK-063).
 */

import { useQuery } from '@tanstack/react-query';
import { getBusinessMetrics } from './api';

/** Stable query key for the business-metrics snapshot. */
export const ADMIN_METRICS_QUERY_KEY = ['admin', 'business-metrics'] as const;

/** Snapshot freshness window — metrics are daily aggregates, 60s is plenty. */
const ADMIN_METRICS_STALE_TIME_MS = 60_000;

/**
 * Query options consumed by `useBusinessMetrics` (exported for unit tests).
 *
 * - `enabled`: the page passes `user.is_superuser === true` so the request
 *   never fires for regular users (client-side UX guard, AC2).
 * - `retry: false`: 403 is terminal (rights revoked / stale flag) — retrying
 *   would just spam the server gate.
 */
export function businessMetricsQueryOptions(enabled: boolean) {
  return {
    queryKey: ADMIN_METRICS_QUERY_KEY,
    queryFn: getBusinessMetrics,
    staleTime: ADMIN_METRICS_STALE_TIME_MS,
    retry: false,
    enabled,
  } as const;
}

/** Fetch the aggregate business metrics snapshot (superuser only). */
export function useBusinessMetrics(enabled: boolean) {
  return useQuery(businessMetricsQueryOptions(enabled));
}
