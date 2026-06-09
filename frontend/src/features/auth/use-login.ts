/**
 * useLogin — mutation hook for POST /auth/jwt/login.
 *
 * On success: invalidates the current-user query so useCurrentUser re-fetches.
 * Returns { mutateAsync, isPending, error }.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { login, type LoginPayload } from './api';
import { CURRENT_USER_QUERY_KEY } from '@/entities/viewer/model';

export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: LoginPayload) => login(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: CURRENT_USER_QUERY_KEY });
    },
  });
}
