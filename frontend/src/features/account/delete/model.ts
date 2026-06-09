import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { v4 as uuidv4 } from "uuid"

import { useAlertStore } from "@/app/providers/use-alert-store"
import { useAuth } from "@/app/providers/use-auth"
import { paths } from "@/app/router/path"

import { deleteAccount } from "./api"

export interface DeleteAccountOptions {
  onSuccess?: () => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

const DELETE_ACCOUNT_MUTATION_KEY = ["delete-account"]

/**
 * Invokes `DELETE /account` for the currently-authenticated user (TrendPulse).
 * The backend deletes the user and all their data (cascade) → 204.
 *
 * On success the auth store is cleared and the SPA redirects to sign-in.
 */
export const useDeleteAccount = (options: DeleteAccountOptions = {}) => {
  const queryClient = useQueryClient()
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)
  const authStore = useAuth()
  const clearAuth = authStore((state) => state.clearAuth)
  const navigate = useNavigate()

  return useMutation({
    mutationKey: DELETE_ACCOUNT_MUTATION_KEY,
    mutationFn: () => deleteAccount(),
    onSuccess: async () => {
      queryClient.clear()
      clearAuth()

      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Account deleted",
        description: "Your account and all your data were removed.",
      })

      await navigate({ to: paths.auth.signIn, replace: true })
      await options.onSuccess?.()
    },
    onError: async (error) => {
      addAlert({
        id: uuidv4(),
        type: "error",
        title: "Couldn't delete account",
        description: error instanceof Error ? error.message : "Unknown error",
      })

      await options.onError?.(error as Error)
    },
  })
}
