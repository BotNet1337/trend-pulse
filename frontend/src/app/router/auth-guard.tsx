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
 * Onboarding redirect (TASK-039): after auth is confirmed, if the user has
 * 0 watchlists AND is not already on /onboarding, redirect to /onboarding.
 * Criterion: watchlists count === 0. No DB flag needed (task doc §Discussion).
 * Direct navigation to /onboarding is always allowed (no blocking).
 *
 * The isSafeRedirect guard on login ensures the `redirect` param can only be
 * an internal path (no open-redirect).
 */
import React from 'react'
import { Outlet, useRouter, useRouterState } from '@tanstack/react-router'

import { useCurrentUser } from '@/entities/viewer/model'
import { useWatchlists } from '@/features/watchlists'
import { paths } from './path'

export const AuthGuard: React.FC = () => {
  const { data, isLoading } = useCurrentUser()
  const router = useRouter()
  const location = useRouterState({ select: (s) => s.location })

  // Fetch watchlists only once auth is confirmed — used to determine if the
  // user should be redirected to /onboarding (0 watchlists = new user).
  const isAuthenticated = !isLoading && !!data
  const { data: watchlists, isLoading: watchlistsLoading } = useWatchlists()

  React.useEffect(() => {
    if (isLoading) return
    if (!data) {
      // Guard against a redirect loop: while this navigate is in flight the
      // guard can re-run with location.href already updated to the sign-in URL
      // (data is still null), which would capture the sign-in URL itself as the
      // `redirect` param — nesting `?redirect=/auth/sign-in?redirect=…` on every
      // re-run. Never redirect to sign-in FROM sign-in; keep the clean original
      // path as the single redirect target.
      if (location.pathname !== paths.auth.signIn) {
        void router.navigate({
          to: paths.auth.signIn,
          search: { redirect: location.href },
          replace: true,
        })
      }
      return
    }

    // Onboarding redirect (TASK-039): 0 watchlists + not already on /onboarding
    // → redirect to /onboarding so new users immediately see value.
    // Wait for watchlists query to finish before deciding (avoid flash-redirect).
    if (!watchlistsLoading && watchlists !== undefined) {
      const isOnOnboarding = location.pathname === paths.onboarding
      if (watchlists.length === 0 && !isOnOnboarding) {
        void router.navigate({ to: paths.onboarding, replace: true })
      }
    }
  }, [isLoading, data, router, location.href, location.pathname,
      watchlists, watchlistsLoading])

  if (isLoading) {
    // Blank screen while determining auth state — avoids FOUC/flash of protected content
    return null
  }

  if (!data) {
    // Redirect is in flight (useEffect); render nothing to avoid flash
    return null
  }

  // Block render while checking watchlists for onboarding redirect — only on
  // routes other than /onboarding itself (to avoid blocking the page that is
  // the redirect target).
  if (
    isAuthenticated &&
    watchlistsLoading &&
    location.pathname !== paths.onboarding
  ) {
    return null
  }

  return <Outlet />
}
