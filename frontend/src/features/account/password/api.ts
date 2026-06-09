import type { AxiosInstance } from "axios"

import { apiClient } from "@/shared/api"

export const changePasswordPath = "/auth/password" as const

export interface ChangePasswordBody {
  currentPassword: string
  newPassword: string
}

export const changePassword = async (
  body: ChangePasswordBody,
  client?: AxiosInstance,
): Promise<void> => {
  const executor = client ?? apiClient

  await executor.patch<void>(changePasswordPath, body)
}
