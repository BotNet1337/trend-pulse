/**
 * AuthProvider — wraps children in the AuthContext and bootstraps auth state.
 *
 * TASK-014 (C2): On mount, fetches GET /users/me to determine if the user is
 * authenticated (httpOnly cookie). On success → calls setAuth to populate the
 * Zustand AuthStore so the TanStack Router beforeLoad guards can read it
 * synchronously. On 401 or error → clearAuth (user stays null).
 *
 * This keeps the router guards synchronous (beforeLoad) while the actual auth
 * source is the backend cookie (no JWT in localStorage).
 */
import React, { useMemo, useEffect, useRef } from 'react'
import { createUseAuthStore, type AuthStore } from '../stores/auth.store'
import { AuthContext } from './use-auth'
import { apiClient } from '@/shared/api'
import type { CurrentUser } from '@/entities/viewer/model'
import type { JwtUser } from '@/entities/user/model'
import type { AxiosError } from 'axios'

export interface AuthProviderProps {
  auth: AuthStore
  children: React.ReactNode
}

/**
 * Map a CurrentUser from GET /users/me to the JwtUser shape used by AuthStore.
 * We keep AuthStore typed as JwtUser so the rest of the app (C3/C5) can extend
 * it without changing the store type. Fields not in CurrentUser are set to
 * synthetic values that make sense for cookie-auth (no real JWT on the client).
 */
function toJwtUser(user: CurrentUser): JwtUser {
  return {
    userId: String(user.id),
    accountId: String(user.id),
    email: user.email,
    provider: 'cookie',
  }
}

export function AuthProvider(props: AuthProviderProps) {
  const useAuth = useMemo(() => createUseAuthStore(props.auth), [props.auth])
  const bootstrapped = useRef(false)

  useEffect(() => {
    // Bootstrap once on mount: check if the user is already authenticated
    // via the httpOnly cookie by calling GET /users/me.
    if (bootstrapped.current) return
    bootstrapped.current = true

    const { setAuth, clearAuth } = props.auth.getState()

    apiClient
      .get<CurrentUser>('/users/me')
      .then((resp) => {
        setAuth(toJwtUser(resp.data))
      })
      .catch((err: unknown) => {
        const axiosErr = err as AxiosError
        // 401 is expected for unauthenticated visitors — clear auth silently.
        if (axiosErr.response?.status !== 401) {
          // Non-401 errors (network, 5xx) — leave user as null (unauthenticated)
          // rather than crashing. The guard will redirect to sign-in.
        }
        clearAuth()
      })
  }, [props.auth])

  return (
    <AuthContext.Provider value={useAuth}>
      {props.children}
    </AuthContext.Provider>
  )
}
