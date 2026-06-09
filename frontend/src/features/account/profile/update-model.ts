import { useMutation } from "@tanstack/react-query"

import type { UpdateUserProfileParams } from "./update-api"

export interface UseUpdateUserProfileOptions {
  onSuccess?: (params: UpdateUserProfileParams) => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

/**
 * Profile update — stub for TrendPulse C2+.
 * Profile name/avatar update endpoints are not yet implemented in the backend.
 * This hook is kept as a stub so account-settings-view compiles without errors.
 */
export const useUpdateUserProfile = (
  options: UseUpdateUserProfileOptions = {},
) => {
  return useMutation({
    mutationKey: ["update-user-profile"],
    mutationFn: async (params: UpdateUserProfileParams): Promise<void> => {
      // Not yet implemented in TrendPulse C1.
      // TODO: implement in C2 when backend exposes PATCH /users/me/profile.
      throw new Error(`Profile update not yet available (userId=${params.userId})`)
    },
    onSuccess: async (_, params) => {
      await options.onSuccess?.(params)
    },
    onError: async (error) => {
      await options.onError?.(error as Error)
    },
  })
}
