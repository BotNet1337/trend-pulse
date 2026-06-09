import type { AxiosInstance } from "axios"

import { apiClient, type OpenApiPathParams } from "@/shared/api"

const mask = "{userId}"

export const deleteAccountPath = `/users/${mask}` as const

export type DeleteAccountPath = typeof deleteAccountPath
export type DeleteAccountParams = OpenApiPathParams<DeleteAccountPath, "delete">

export const deleteAccount = async (
  params: DeleteAccountParams,
  client?: AxiosInstance,
): Promise<void> => {
  const executor = client ?? apiClient

  await executor.delete<void>(deleteAccountPath.replace(mask, params.userId))
}
