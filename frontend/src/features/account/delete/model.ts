import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { v4 as uuidv4 } from "uuid"

import { useAlertStore } from "@/app/providers/use-alert-store"
import { useAuth } from "@/app/providers/use-auth"
import { paths } from "@/app/router/path"

import {
  deleteAccount,
  deleteAccountPath,
  type DeleteAccountParams,
} from "./api"

export interface DeleteAccountOptions {
  onSuccess?: (params: DeleteAccountParams) => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

/**
 * Invokes `DELETE /users/:userId` for the currently-authenticated user. The
 * backend soft-deletes the user, revokes refresh sessions, and (via NATS
 * cascade) marks owned workspaces / posts / channels as `state='deleted'`.
 *
 * On success the auth store is cleared and the SPA redirects to sign-in —
 * the cookie may still be live for a moment until the API layer notices the
 * 401 from a follow-up request, so we proactively wipe state here.
 */
export const useDeleteAccount = (options: DeleteAccountOptions = {}) => {
  const queryClient = useQueryClient()
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)
  const authStore = useAuth()
  const clearAuth = authStore((state) => state.clearAuth)
  const navigate = useNavigate()

  return useMutation({
    mutationKey: deleteAccountPath.split("/"),
    mutationFn: (params: DeleteAccountParams) => deleteAccount(params),
    onSuccess: async (_, params) => {
      queryClient.clear()
      clearAuth()

      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Account deleted",
        description: "Your account and all owned workspaces were removed.",
      })

      await navigate({ to: paths.auth.signIn, replace: true })
      await options.onSuccess?.(params)
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
