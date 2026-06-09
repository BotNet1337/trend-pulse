/**
 * AuthProvider — wraps children in the AuthContext and bootstraps auth state.
 *
 * TASK-014 (C2): Subscribes to the react-query useCurrentUser cache (single
 * source of truth) and mirrors the result into the Zustand AuthStore so that
 * TanStack Router beforeLoad guards can read it synchronously.
 *
 * No direct axios call here — the bootstrap is handled by AuthGuard (which
 * already calls useCurrentUser). This eliminates the duplicate GET /users/me
 * on cold-start and keeps redirect logic in one place (guard only).
 */
import React, { useMemo, useEffect } from 'react'
import { createUseAuthStore, type AuthStore } from '../stores/auth.store'
import { AuthContext } from './use-auth'
import { useCurrentUser } from '@/entities/viewer/model'
import type { CurrentUser } from '@/entities/viewer/model'
import type { JwtUser } from '@/entities/user/model'

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

/**
 * Inner component — must be a child of QueryClientProvider so that
 * useCurrentUser (react-query) is available.
 */
function AuthSync({ auth }: { auth: AuthStore }) {
  const { data } = useCurrentUser()

  useEffect(() => {
    const { setAuth, clearAuth } = auth.getState()
    if (data) {
      setAuth(toJwtUser(data))
    } else if (data === null) {
      // null means 401 (unauthenticated); undefined means still loading — skip.
      clearAuth()
    }
  }, [data, auth])

  return null
}

export function AuthProvider(props: AuthProviderProps) {
  const useAuth = useMemo(() => createUseAuthStore(props.auth), [props.auth])

  return (
    <AuthContext.Provider value={useAuth}>
      <AuthSync auth={props.auth} />
      {props.children}
    </AuthContext.Provider>
  )
}
