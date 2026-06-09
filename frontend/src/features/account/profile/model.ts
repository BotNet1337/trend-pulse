import { useQuery } from "@tanstack/react-query"

import { useAuth } from "@/app/providers/use-auth"

import { findUser, findUserPath, type FindUserResponse } from "./api"

export const meQueryKey = (userId: string): ReadonlyArray<string> =>
  [findUserPath, userId] as const

/**
 * Loads the currently-authenticated user via `GET /users/:userId`. Source
 * of truth for the auth-store is the JWT (which only carries id + email +
 * provider); this query fetches the richer profile (name, avatar, timestamps)
 * from the IAM module.
 */
export const useMe = () => {
  const authStore = useAuth()
  const userId = authStore((state) => state.user?.userId ?? "")

  return useQuery<FindUserResponse>({
    queryKey: meQueryKey(userId),
    queryFn: () => findUser({ userId }),
    enabled: userId.length > 0,
  })
}
