import { useQuery } from "@tanstack/react-query"

import { useAuth } from "@/app/providers/use-auth"

import { findUser, findMyTenantPath, type FindUserResponse } from "./api"

export const meQueryKey = (userId: string): ReadonlyArray<string> =>
  [findMyTenantPath, userId] as const

/**
 * Returns the current user's tenant info via GET /users/me/tenant.
 * Enabled only when the auth store has a userId (i.e. user is logged in).
 */
export const useMe = () => {
  const authStore = useAuth()
  const userId = authStore((state) => state.user?.userId ?? "")

  return useQuery<FindUserResponse>({
    queryKey: meQueryKey(userId),
    queryFn: () => findUser(),
    enabled: userId.length > 0,
  })
}
