/**
 * Sign-in page — TASK-014 (C2) implementation.
 *
 * Endpoints:
 *  - POST /auth/jwt/login  form-urlencoded (username + password) → httpOnly cookie
 *  - Google: browser redirect to /api/auth/google/authorize (no fetch, no secrets in bundle)
 *
 * Guard: on 401 → apiClient interceptor redirects here with ?redirect=<path>.
 * After login: navigate to `redirect` param (internal-only via isSafeRedirect).
 * Forgot password link enabled: backend verify/reset routers mounted in TASK-026.
 */
import React, { useState } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'

import { paths } from '@/app/router/path'
import { isSafeRedirect } from '@/shared/api'
import { AuthFrame } from './auth-frame'
import { useLogin, navigateToGoogleAuth } from '@/features/auth'
import { CURRENT_USER_QUERY_KEY } from '@/entities/viewer/model'

export const SignInPage: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const search = useSearch({ strict: false }) as { redirect?: string }

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const loginMutation = useLogin()

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await loginMutation.mutateAsync({ email, password })
      // Invalidate current-user so guard/viewer re-evaluates immediately
      await queryClient.invalidateQueries({ queryKey: CURRENT_USER_QUERY_KEY })
      // Harden against open-redirect: only honour internal same-origin paths
      // from the attacker-controllable `?redirect=` param (A01 / unvalidated redirect).
      const redirectTo =
        search.redirect && isSafeRedirect(search.redirect) ? search.redirect : paths.home
      await navigate({ to: redirectTo, replace: true })
    } catch {
      // Static message — never leak whether the email exists (AC5 / no-enumeration).
      setError('Invalid email or password.')
    }
  }

  const pending = loginMutation.isPending

  return (
    <AuthFrame>
      <section className="fs-card fs-auth-card" aria-label="Sign in">
        <div className="fs-auth-head">
          <h1>Welcome back</h1>
          <p>Enter your credentials to sign in to your account</p>
        </div>

        <form onSubmit={(e) => void onSubmit(e)} className="fs-auth-form">
          <div className="fs-field">
            <label className="fs-label" htmlFor="email">
              Email
            </label>
            <input
              className="fs-input"
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={pending}
              placeholder="you@example.com"
            />
          </div>
          <div className="fs-field">
            <label className="fs-label" htmlFor="password">
              Password
            </label>
            <input
              className="fs-input"
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={pending}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="fs-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="fs-btn fs-btn--primary fs-btn--block" disabled={pending}>
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {/* Google OAuth — browser redirect, no fetch, no secrets in bundle */}
        <div className="fs-auth-divider" aria-hidden="true">
          or
        </div>

        <button
          type="button"
          className="fs-btn fs-btn--secondary fs-btn--block"
          onClick={() => navigateToGoogleAuth()}
          aria-label="Sign in with Google"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="18"
            height="18"
            aria-hidden="true"
          >
            <path
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              fill="#4285F4"
            />
            <path
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              fill="#34A853"
            />
            <path
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
              fill="#FBBC05"
            />
            <path
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              fill="#EA4335"
            />
          </svg>
          Sign in with Google
        </button>

        <div className="fs-auth-links">
          <span>
            Don&apos;t have an account? <Link to={paths.auth.signUp}>Sign up</Link>
          </span>
          <span>
            <Link to={paths.auth.forgotPassword}>Forgot password?</Link>
          </span>
        </div>
      </section>
    </AuthFrame>
  )
}
