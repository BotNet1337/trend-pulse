import type { AxiosInstance } from "axios"

import { apiClient, type OpenApiPathParams } from "@/shared/api"
import type { User } from "./model"

const mask = "{userId}"

export const findUserByIdPath = `/users/${mask}` as const

export type FindUserByIdPath = typeof findUserByIdPath

export type FindUserByIdPathParams = OpenApiPathParams<FindUserByIdPath, "get">

/**
 * Response is typed via the `User` entity. The OpenAPI spec doesn't
 * currently carry a response schema for this endpoint (no
 * `@ApiResponse({ type: UserDto })` on the backend controller), so
 * `OpenApiResponse<...>` would resolve to `never`. Once that decorator is
 * wired, swap to `OpenApiResponse<FindUserByIdPath, "get">`.
 */
export const findUserById = async (
  pathParams: FindUserByIdPathParams,
  client?: AxiosInstance,
): Promise<User> => {
  const executor = client ?? apiClient
  const path = findUserByIdPath.replace(mask, pathParams.userId)
  const response = await executor.get<User>(path)
  return response.data
}
