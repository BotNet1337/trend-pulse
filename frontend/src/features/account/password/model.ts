import { useMutation } from "@tanstack/react-query"
import { v4 as uuidv4 } from "uuid"

import { useAlertStore } from "@/app/providers/use-alert-store"

import {
  changePassword,
  changePasswordPath,
  type ChangePasswordBody,
} from "./api"

export interface UseChangePasswordOptions {
  onSuccess?: () => void | Promise<void>
  onError?: (error: Error) => void | Promise<void>
}

export const useChangePassword = (options: UseChangePasswordOptions = {}) => {
  const alertStore = useAlertStore()
  const addAlert = alertStore((state) => state.add)

  return useMutation({
    mutationKey: changePasswordPath.split("/"),
    mutationFn: (body: ChangePasswordBody) => changePassword(body),
    onSuccess: async () => {
      addAlert({
        id: uuidv4(),
        type: "success",
        title: "Password updated",
      })

      await options.onSuccess?.()
    },
    onError: async (error) => {
      addAlert({
        id: uuidv4(),
        type: "error",
        title: "Couldn't update password",
        description: error instanceof Error ? error.message : "Unknown error",
      })

      await options.onError?.(error as Error)
    },
  })
}
