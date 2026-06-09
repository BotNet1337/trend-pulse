/**
 * React-Query hooks for packs — list catalog, subscribe, unsubscribe.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { listPacks, subscribePack, unsubscribePack } from './api';

/** Stable query key for the packs catalog list. */
export const PACKS_QUERY_KEY = ['packs', 'catalog'] as const;

// ─── Queries ──────────────────────────────────────────────────────────────────

/** List the full curated pack catalog. */
export function usePacks() {
  return useQuery({
    queryKey: PACKS_QUERY_KEY,
    queryFn: listPacks,
    staleTime: 60_000,
  });
}

// ─── Mutations ────────────────────────────────────────────────────────────────

/**
 * Subscribe to a pack — POST /packs/{slug}/subscribe.
 * On success, invalidates both packs catalog and watchlists (new rows added).
 */
export function useSubscribePack() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (slug: string) => subscribePack(slug),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PACKS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
}

/**
 * Unsubscribe from a pack — DELETE /packs/{slug}/subscribe.
 * On success, invalidates watchlists (rows removed).
 */
export function useUnsubscribePack() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (slug: string) => unsubscribePack(slug),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PACKS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });
}
