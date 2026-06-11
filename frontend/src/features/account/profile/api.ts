import type { AxiosInstance } from "axios"

import { apiClient, type OpenApiResponse } from "@/shared/api"

// Schema key (gen.types `paths`) carries the /v1 prefix; the runtime request is
// relative to apiClient baseURL (/api/v1), so the two constants differ on purpose.
export const findMyTenantSchemaPath = "/v1/users/me/tenant" as const
export const findMyTenantPath = "/users/me/tenant" as const
export type FindMyTenantPath = typeof findMyTenantSchemaPath
export type FindUserResponse = OpenApiResponse<FindMyTenantPath, "get">

/**
 * GET /users/me/tenant — returns the current authenticated user's tenant id.
 * This is the only user-info endpoint available in TrendPulse C1.
 * Profile name/avatar features are planned for C2+.
 */
export const findUser = async (
  client?: AxiosInstance,
): Promise<FindUserResponse> => {
  const executor = client ?? apiClient
  const response = await executor.get<FindUserResponse>(findMyTenantPath)
  return response.data
}
