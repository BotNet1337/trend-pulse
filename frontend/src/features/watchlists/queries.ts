/**
 * React-Query hooks for watchlists — list, get, create, update, delete.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  listWatchlists,
  getWatchlist,
  createWatchlist,
  updateWatchlist,
  deleteWatchlist,
} from './api';
import {
  WATCHLISTS_QUERY_KEY,
  watchlistQueryKey,
  type WatchlistCreate,
  type WatchlistUpdate,
} from '@/entities/watchlist/model';

// ─── Queries ──────────────────────────────────────────────────────────────────

/** List all caller's watchlists. */
export function useWatchlists() {
  return useQuery({
    queryKey: WATCHLISTS_QUERY_KEY,
    queryFn: listWatchlists,
    staleTime: 30_000,
  });
}

/** Get a single watchlist by id. Throws on 404 (caught by the page). */
export function useWatchlist(id: number) {
  return useQuery({
    queryKey: watchlistQueryKey(id),
    queryFn: () => getWatchlist(id),
    staleTime: 30_000,
    retry: (failureCount, error) => {
      // Don't retry 404 — it's a terminal state
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 404) return false;
      return failureCount < 2;
    },
  });
}

// ─── Mutations ────────────────────────────────────────────────────────────────

/** Create a watchlist — POST /watchlists. */
export function useCreateWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: WatchlistCreate) => createWatchlist(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS_QUERY_KEY });
    },
  });
}

/** Update a watchlist — PATCH /watchlists/{id}. */
export function useUpdateWatchlist(id: number) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: WatchlistUpdate) => updateWatchlist(id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(watchlistQueryKey(id), updated);
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS_QUERY_KEY });
    },
  });
}

/** Delete a watchlist — DELETE /watchlists/{id}. */
export function useDeleteWatchlist() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => deleteWatchlist(id),
    onSuccess: (_data, id) => {
      queryClient.removeQueries({ queryKey: watchlistQueryKey(id) });
      void queryClient.invalidateQueries({ queryKey: WATCHLISTS_QUERY_KEY });
    },
    // 404 on already-deleted is a soft failure — still remove from cache
    onError: (_error, id) => {
      const status = (_error as { response?: { status?: number } }).response?.status;
      if (status === 404) {
        queryClient.removeQueries({ queryKey: watchlistQueryKey(id) });
        void queryClient.invalidateQueries({ queryKey: WATCHLISTS_QUERY_KEY });
      }
    },
  });
}
