import type { AxiosInstance } from "axios"

import {
  apiClient,
  type OpenApiPathParams,
  type OpenApiResponse,
} from "@/shared/api"

const mask = "{userId}"

export const findUserPath = `/users/${mask}` as const

export type FindUserPath = typeof findUserPath
export type FindUserParams = OpenApiPathParams<FindUserPath, "get">
export type FindUserResponse = OpenApiResponse<FindUserPath, "get">

export const findUser = async (
  params: FindUserParams,
  client?: AxiosInstance,
): Promise<FindUserResponse> => {
  const executor = client ?? apiClient

  const response = await executor.get<FindUserResponse>(
    findUserPath.replace(mask, params.userId),
  )

  return response.data
}
