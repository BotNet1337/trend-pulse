/**
 * React-Query hooks for API keys (TASK-065) — list, create, revoke.
 *
 * Cache discipline: the list cache holds only `ApiKeyRead` (no plaintext).
 * `useCreateApiKey` returns `ApiKeyCreated` to the caller; the component must
 * move the plaintext into local modal state and `reset()` the mutation so the
 * secret does not linger in mutation state (see api-keys-section.tsx).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createApiKey, listApiKeys, revokeApiKey } from './api';

/** Stable query key for the API-keys list. */
export const API_KEYS_QUERY_KEY = ['api-keys'] as const;

/** Cache freshness window for the keys list (ms). */
const API_KEYS_STALE_TIME_MS = 60_000;

// ─── Queries ──────────────────────────────────────────────────────────────────

/** List the current user's API keys (masked — prefix only). */
export function useApiKeys(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: listApiKeys,
    staleTime: API_KEYS_STALE_TIME_MS,
    enabled: options?.enabled ?? true,
  });
}

// ─── Mutations ────────────────────────────────────────────────────────────────

/** Issue a new API key — POST /api-keys. Invalidates the list on success. */
export function useCreateApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (name: string) => createApiKey(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
    },
  });
}

/**
 * Revoke an API key — DELETE /api-keys/{key_id}.
 * Invalidates the list on success AND on error: a 404 means the key was already
 * revoked elsewhere, so the list must re-sync with the server either way.
 */
export function useRevokeApiKey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (keyId: number) => revokeApiKey(keyId),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
    },
  });
}
