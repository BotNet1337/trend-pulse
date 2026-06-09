import { useMutation, useQueryClient } from "@tanstack/react-query"
import { v4 as uuidv4 } from "uuid"

import { useAlertStore } from "@/app/providers/use-alert-store"

import { meQueryKey } from "./model"
import {
  updateUserProfile,
  updateUserProfilePath,
  type UpdateUserProfileParams,
} from "./update-api"

export interface UseUpdateUserProfileOptions {
  onSuccess?: (params: UpdateUserProfileParams) => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

/**
 * Invokes `PATCH /users/:userId/profile` to update the display name. On
 * success refreshes the `useMe()` query and emits a success alert.
 */
export const useUpdateUserProfile = (
  options: UseUpdateUserProfileOptions = {},
) => {
  const queryClient = useQueryClient()
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)

  return useMutation({
    mutationKey: updateUserProfilePath.split("/"),
    mutationFn: (params: UpdateUserProfileParams) => updateUserProfile(params),
    onSuccess: async (_, params) => {
      await queryClient.invalidateQueries({
        queryKey: meQueryKey(params.userId),
      })

      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Display name updated",
      })

      await options.onSuccess?.(params)
    },
    onError: async (error) => {
      addAlert({
        id: uuidv4(),
        type: "error",
        title: "Couldn't update display name",
        description: error instanceof Error ? error.message : "Unknown error",
      })

      await options.onError?.(error as Error)
    },
  })
}
