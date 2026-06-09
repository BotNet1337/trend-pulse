import type { AxiosInstance } from "axios"

import { apiClient } from "@/shared/api"

/**
 * DELETE /account — deletes the authenticated user and all their data (cascade).
 * Protected: requires auth cookie. Returns 204 on success.
 * TrendPulse backend endpoint: api/routes.py account_router.
 */
export const deleteAccount = async (
  client?: AxiosInstance,
): Promise<void> => {
  const executor = client ?? apiClient
  await executor.delete<void>("/account")
}
