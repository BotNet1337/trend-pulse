import type { AxiosInstance } from "axios"

import { apiClient } from "@/shared/api"

export const requestEmailChangePath = "/auth/email/request-change" as const
export const confirmEmailChangePath = "/auth/email/confirm-change" as const

export interface RequestEmailChangeBody {
  currentPassword: string
  newEmail: string
}

export interface ConfirmEmailChangeBody {
  token: string
}

export const requestEmailChange = async (
  body: RequestEmailChangeBody,
  client?: AxiosInstance,
): Promise<void> => {
  const executor = client ?? apiClient
  await executor.post<void>(requestEmailChangePath, body)
}

export const confirmEmailChange = async (
  body: ConfirmEmailChangeBody,
  client?: AxiosInstance,
): Promise<void> => {
  const executor = client ?? apiClient
  await executor.post<void>(confirmEmailChangePath, body)
}
