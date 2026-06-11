/**
 * React-Query hooks for alerts — list (with cursor pagination/"load more") + detail.
 * Types from gen.types (C1 invariant).
 *
 * TASK-020: useAlerts migrated from offset/total to cursor (next_cursor) keyset pagination.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationOptions,
} from '@tanstack/react-query';
import { listAlerts, getAlert, sendFeedback } from './api';
import { ALERTS_QUERY_KEY, alertQueryKey } from '@/entities/alert/model';
import type { AlertListResponse, AlertRead } from '@/entities/alert/model';

/** Web 👍/👎 verdict — matches the backend `feedback` string values. */
export type FeedbackVerdict = 'up' | 'down';

/** Arguments for a single feedback mutation: the bearer token + the verdict it
 *  encodes (verdict drives the optimistic cache write). */
export interface SendFeedbackArgs {
  token: string;
  verdict: FeedbackVerdict;
}

/** Optimistic-update rollback context: the alert snapshot before the mutation. */
interface FeedbackMutationContext {
  previous: AlertRead | undefined;
}

// Default page size for the feed — matches backend DEFAULT_ALERTS_PAGE_SIZE.
const ALERTS_PAGE_SIZE = 20;

// ─── useAlerts — infinite / "load more" pagination ───────────────────────────

/**
 * Paginated alerts feed (cursor-based keyset pagination, TASK-020).
 *
 * Uses `useInfiniteQuery` so the UI can show "Load more" or infinite scroll.
 * The first page is fetched immediately; subsequent pages are fetched on demand.
 *
 * `history_unavailable` is surfaced from the first page response so the UI
 * can render the plan-upgrade upsell without inspecting individual pages.
 *
 * Pagination: passes `next_cursor` from each page response as the `cursor`
 * parameter of the next request. Stops when `next_cursor` is null.
 */
// First page has no cursor. Exported so the unit test exercises the real value
// (not a copy), keeping the stop-condition contract honest.
export const ALERTS_INITIAL_PAGE_PARAM: string | null = null;

/** Next page param for the alerts feed: the page's `next_cursor`, or undefined
 *  (NOT null) to stop — `useInfiniteQuery` halts when this returns undefined. */
export function alertsNextPageParam(lastPage: AlertListResponse): string | undefined {
  return lastPage.next_cursor ?? undefined;
}

export function useAlerts() {
  return useInfiniteQuery({
    queryKey: ALERTS_QUERY_KEY,
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      listAlerts({ cursor: pageParam ?? undefined, limit: ALERTS_PAGE_SIZE }),
    initialPageParam: ALERTS_INITIAL_PAGE_PARAM,
    getNextPageParam: alertsNextPageParam,
    staleTime: 30_000,
  });
}

// ─── useAlert — single alert detail ──────────────────────────────────────────

/** Get a single alert by id. Does NOT throw — error is handled by the detail page. */
export function useAlert(id: number) {
  return useQuery({
    queryKey: alertQueryKey(id),
    queryFn: () => getAlert(id),
    enabled: !Number.isNaN(id),
    staleTime: 30_000,
    // Never throw — the detail page reads `error` and renders not-found state.
    throwOnError: false,
    retry: (failureCount, error) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 404) return false;
      return failureCount < 2;
    },
  });
}

// ─── useSendFeedback — optimistic 👍/👎 mutation ──────────────────────────────

/**
 * Build the canonical optimistic-update mutation options for alert feedback.
 *
 * Extracted from the hook so the optimistic/rollback logic can be unit-tested
 * against a real QueryClient (driven via a MutationObserver) without mounting
 * React — the test exercises THESE options, not a copy.
 *
 * onMutate writes the new verdict into the `alertQueryKey(alertId)` cache
 * immediately (after cancelling in-flight refetches and snapshotting the prior
 * value); onError rolls back to the snapshot; onSettled invalidates so the cache
 * always reconverges with the server (even on success).
 */
export function feedbackMutationOptions(
  queryClient: QueryClient,
  alertId: number,
): UseMutationOptions<void, Error, SendFeedbackArgs, FeedbackMutationContext> {
  const queryKey = alertQueryKey(alertId);
  return {
    mutationFn: ({ token }: SendFeedbackArgs) => sendFeedback(token),
    onMutate: async ({ verdict }: SendFeedbackArgs) => {
      // Cancel in-flight refetches so they don't clobber the optimistic write.
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<AlertRead>(queryKey);
      if (previous) {
        // Immutable update — new object, never mutate the cached one.
        queryClient.setQueryData<AlertRead>(queryKey, { ...previous, feedback: verdict });
      }
      return { previous };
    },
    onError: (_error, _args, context) => {
      // Roll back to the pre-mutation snapshot.
      if (context) {
        queryClient.setQueryData<AlertRead>(queryKey, context.previous);
      }
    },
    onSettled: () => {
      // Always reconcile with the server (refresh tokens + canonical verdict).
      void queryClient.invalidateQueries({ queryKey });
    },
  };
}

/**
 * Record alert feedback with a canonical TanStack optimistic update.
 *
 * The mutation is idempotent — re-tapping an already-active verdict still sends
 * (the backend UPSERT is last-write-wins). See `feedbackMutationOptions`.
 */
export function useSendFeedback(alertId: number) {
  const queryClient = useQueryClient();
  return useMutation(feedbackMutationOptions(queryClient, alertId));
}
