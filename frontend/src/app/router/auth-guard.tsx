/**
 * AuthGuard — component-level guard for protected routes (TASK-014 C2).
 *
 * Replaces the sync `beforeLoad` check so the guard works with httpOnly-cookie
 * auth: the auth state is determined by GET /users/me (useCurrentUser), not by
 * a JWT payload in localStorage.
 *
 * States:
 *  - isLoading → show a blank/spinner while /users/me resolves (cold-start)
 *  - data === null (401) → redirect to /auth/sign-in?redirect=<path>
 *  - data present → render children (authenticated)
 *
 * The isSafeRedirect guard on login ensures the `redirect` param can only be
 * an internal path (no open-redirect).
 */
import React from 'react'
import { Outlet, useRouter, useRouterState } from '@tanstack/react-router'

import { useCurrentUser } from '@/entities/viewer/model'
import { paths } from './path'

export const AuthGuard: React.FC = () => {
  const { data, isLoading } = useCurrentUser()
  const router = useRouter()
  const location = useRouterState({ select: (s) => s.location })

  React.useEffect(() => {
    if (isLoading) return
    if (!data) {
      void router.navigate({
        to: paths.auth.signIn,
        search: { redirect: location.href },
        replace: true,
      })
    }
  }, [isLoading, data, router, location.href])

  if (isLoading) {
    // Blank screen while determining auth state — avoids FOUC/flash of protected content
    return null
  }

  if (!data) {
    // Redirect is in flight (useEffect); render nothing to avoid flash
    return null
  }

  return <Outlet />
}
