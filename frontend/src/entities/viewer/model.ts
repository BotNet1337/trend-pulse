// Re-export legacy types that were originally declared here and are imported
// by other modules (theme.context, alert.store, viewer/ui/alert).
// These types belong semantically to their respective domains but are kept
// here for backward compatibility until a future refactor relocates them.
export type Theme = 'dark' | 'light' | 'system';
export type AlertType = 'success' | 'error';
export interface AlertItem {
  id: string;
  type: AlertType;
  title: string;
  description?: string;
}

/**
 * Viewer entity — current authenticated user from GET /users/me.
 *
 * TASK-014 (C2): useCurrentUser is the single source of truth for
 * authenticated user state in the SPA. Used by:
 *  - guards (router) — detect 401 → redirect to /auth/sign-in
 *  - pages — show email / plan / is_verified
 *  - C3/C5 (future) — plan gating and billing
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient, SKIP_REDIRECT_ON_401 } from '@/shared/api';
import type { components } from '@/shared/api/gen.types';
import type { AxiosError } from 'axios';

/**
 * CurrentUser — derived from the generated OpenAPI schema (C1 invariant).
 * Source of truth: GET /users/me → UserMeResponse (backend schema).
 * Do NOT declare this manually; use the generated type.
 */
export type CurrentUser = components['schemas']['UserMeResponse'];

/** Stable query key for cache invalidation (logout, login). */
export const CURRENT_USER_QUERY_KEY = ['viewer', 'me'] as const;

/**
 * Fetch the current authenticated user from GET /users/me.
 * Returns null on 401 (unauthenticated), throws on other errors.
 */
async function fetchCurrentUser(): Promise<CurrentUser | null> {
  try {
    // Tag the request so the interceptor skips its own 401-redirect.
    // Redirect responsibility for this path belongs to AuthGuard.
    const resp = await apiClient.get<CurrentUser>('/users/me', {
      [SKIP_REDIRECT_ON_401]: true,
    } as Record<string, unknown>);
    return resp.data;
  } catch (error: unknown) {
    const axiosError = error as AxiosError;
    if (axiosError.response?.status === 401) {
      return null;
    }
    throw error;
  }
}

/**
 * useCurrentUser — react-query hook for the authenticated user profile.
 *
 * - data: CurrentUser | null | undefined
 *   null  → 401 (not authenticated)
 *   undefined → still loading
 * - staleTime: 60s — avoids hammering /users/me on every render
 * - retry: false — 401 is a known terminal state, no point retrying
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: CURRENT_USER_QUERY_KEY,
    queryFn: fetchCurrentUser,
    staleTime: 60_000,
    retry: false,
  });
}
