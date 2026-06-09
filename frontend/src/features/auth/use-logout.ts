/**
 * useLogout — mutation hook for POST /auth/jwt/logout.
 *
 * On success:
 *  1. Clears the current-user react-query cache (useCurrentUser → null → guard redirects)
 *  2. Clears AuthStore (anonymousLayoutRoute fast-path)
 *  3. Hard-redirects to /auth/sign-in (ensures clean state even if guard is slow)
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { logout } from './api';
import { useAuth } from '@/app/providers/use-auth';
import { CURRENT_USER_QUERY_KEY } from '@/entities/viewer/model';
import { paths } from '@/app/router/path';

export function useLogout() {
  const queryClient = useQueryClient();
  const authStore = useAuth();
  const clearAuth = authStore((state) => state.clearAuth);

  return useMutation({
    mutationFn: () => logout(),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: CURRENT_USER_QUERY_KEY });
      clearAuth();
      window.location.assign(paths.auth.signIn);
    },
    onError: () => {
      // Even on error, clear local state and redirect — backend may have already
      // cleared the cookie (idempotent logout is safe to force locally).
      queryClient.removeQueries({ queryKey: CURRENT_USER_QUERY_KEY });
      clearAuth();
      window.location.assign(paths.auth.signIn);
    },
  });
}
