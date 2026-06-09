import type { AxiosInstance } from "axios"

import { apiClient } from "@/shared/api"

import type { FindUserResponse } from "./api"

const mask = "{userId}"

export const updateUserProfilePath = `/users/${mask}/profile` as const

export interface UpdateUserProfileParams {
  userId: string
  name: string
}

export const updateUserProfile = async (
  params: UpdateUserProfileParams,
  client?: AxiosInstance,
): Promise<FindUserResponse> => {
  const executor = client ?? apiClient

  const response = await executor.patch<FindUserResponse>(
    updateUserProfilePath.replace(mask, params.userId),
    { name: params.name },
  )

  return response.data
}
