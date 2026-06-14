/**
 * Sign-up page — TASK-014 (C2) + TASK-046 (referral ref propagation).
 *
 * Endpoint: POST /auth/register JSON { email, password, referrer_code? }
 * On success: redirect to /auth/sign-in so user can log in (register does NOT
 * auto-login — fastapi-users returns UserRead, not a cookie).
 * On duplicate email: backend returns 400; shown as friendly error (no enumeration).
 *
 * Referral flow (TASK-046):
 *  1. On mount: read ?ref= from URL → persist to localStorage('referrer_code').
 *  2. On submit: include stored referrer_code in the register payload if present.
 *  3. On success: clear localStorage('referrer_code').
 *
 * NOTE: payload field renamed from 'ref_code' to 'referrer_code' (TASK-046 G2 fix)
 * to avoid colliding with the backend User.ref_code ORM column.
 */
import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'

import { paths } from '@/app/router/path'
import { AuthFrame } from './auth-frame'
import { register } from '@/features/auth'

/**
 * localStorage key for storing an incoming referral code across page loads.
 * Key name matches the payload field 'referrer_code' (TASK-046 G2 fix).
 */
const REF_CODE_STORAGE_KEY = 'referrer_code'

/**
 * Plausible custom event for the sign-up funnel (TASK-068). Name must match the
 * Plausible goal and the landing-side constant EVENT_SIGN_UP_CLICK.
 */
const SIGN_UP_CLICK_EVENT = 'sign_up_click'

/**
 * Fire-and-forget Plausible event (TASK-068). Single call-site, so this stays a
 * local helper instead of a shared package. Guaranteed no-op when the analytics
 * script is blocked or disabled — sign-up must never break on analytics.
 */
function trackSignUpClick(): void {
  try {
    ;(window as Window & { plausible?: (event: string) => void }).plausible?.(SIGN_UP_CLICK_EVENT)
  } catch {
    // Analytics must never affect the auth flow.
  }
}

export const SignUpPage: React.FC = () => {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  // On mount: capture ?ref= from URL into localStorage for persistence across
  // OAuth redirects or page reloads. The URL param takes precedence if present.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const refFromUrl = params.get('ref')
    if (refFromUrl) {
      localStorage.setItem(REF_CODE_STORAGE_KEY, refFromUrl)
    }
  }, [])

  const registerMutation = useMutation({
    mutationFn: () => {
      const storedRef = localStorage.getItem(REF_CODE_STORAGE_KEY) ?? undefined
      return register({ email, password, referrer_code: storedRef })
    },
  })

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    trackSignUpClick()
    try {
      await registerMutation.mutateAsync()
      // Clear the stored referral code after successful registration (single-use).
      localStorage.removeItem(REF_CODE_STORAGE_KEY)
      await navigate({ to: paths.auth.signIn, replace: true })
    } catch {
      // Static message — never reveal whether the email already exists (AC5 / no-enumeration).
      setError('Could not complete registration. Please try again.')
    }
  }

  const pending = registerMutation.isPending

  return (
    <AuthFrame>
      <section className="fs-card fs-auth-card" aria-label="Sign up">
        <div className="fs-auth-head">
          <h1>Create your account</h1>
          <p>Start tracking viral content from Telegram</p>
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
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={pending}
              placeholder="••••••••"
              minLength={3}
            />
          </div>

          {error && (
            <p className="fs-error" role="alert">
              {error}
            </p>
          )}

          <button type="submit" className="fs-btn fs-btn--primary fs-btn--block" disabled={pending}>
            {pending ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <div className="fs-auth-links">
          <span>
            Already have an account? <Link to={paths.auth.signIn}>Sign in</Link>
          </span>
        </div>
      </section>
    </AuthFrame>
  )
}
