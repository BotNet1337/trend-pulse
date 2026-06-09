import { useMutation } from "@tanstack/react-query"
import { v4 as uuidv4 } from "uuid"

import { useAlertStore } from "@/app/providers/use-alert-store"

import {
  confirmEmailChange,
  confirmEmailChangePath,
  requestEmailChange,
  requestEmailChangePath,
  type ConfirmEmailChangeBody,
  type RequestEmailChangeBody,
} from "./api"

export interface UseRequestEmailChangeOptions {
  onSuccess?: (newEmail: string) => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

export const useRequestEmailChange = (
  options: UseRequestEmailChangeOptions = {},
) => {
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)

  return useMutation({
    mutationKey: requestEmailChangePath.split("/"),
    mutationFn: (body: RequestEmailChangeBody) => requestEmailChange(body),
    onSuccess: async (_data, variables) => {
      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Confirmation email sent",
        description: `We sent a confirm link to ${variables.newEmail}.`,
      })

      await options.onSuccess?.(variables.newEmail)
    },
    onError: async (error) => {
      addAlert({
        id: uuidv4(),
        type: "error",
        title: "Couldn't request email change",
        description: error instanceof Error ? error.message : "Unknown error",
      })

      await options.onError?.(error as Error)
    },
  })
}

export interface UseConfirmEmailChangeOptions {
  onSuccess?: () => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

export const useConfirmEmailChange = (
  options: UseConfirmEmailChangeOptions = {},
) => {
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)

  return useMutation({
    mutationKey: confirmEmailChangePath.split("/"),
    mutationFn: (body: ConfirmEmailChangeBody) => confirmEmailChange(body),
    onSuccess: async () => {
      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Email changed",
        description: "Sign in with the new email next time.",
      })

      await options.onSuccess?.()
    },
    onError: async (error) => {
      addAlert({
        id: uuidv4(),
        type: "error",
        title: "Couldn't confirm email change",
        description: error instanceof Error ? error.message : "Unknown error",
      })

      await options.onError?.(error as Error)
    },
  })
}
