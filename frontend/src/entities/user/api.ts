import type { AxiosInstance } from "axios"

import { apiClient } from "@/shared/api"
import type { components } from "@/shared/api/gen.types"

export type TenantResponse = components["schemas"]["TenantResponse"]

/**
 * GET /users/me/tenant — returns the current user's tenant identity.
 * Protected: requires auth cookie (fastapiusersauth). Returns 401 without it.
 */
export const getMyTenant = async (
  client?: AxiosInstance,
): Promise<TenantResponse> => {
  const executor = client ?? apiClient
  const response = await executor.get<TenantResponse>("/users/me/tenant")
  return response.data
}
