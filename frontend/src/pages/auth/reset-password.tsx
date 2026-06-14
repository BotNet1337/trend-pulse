/**
 * Reset password page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useState } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { AuthFrame } from './auth-frame'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'

export const ResetPasswordPage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string; email?: string }
  const navigate = useNavigate()
  const { token, email } = search

  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (!token) {
    return <SomethingWentWrongPage />
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await apiClient.post('/auth/reset-password', { token, password })
      await navigate({ to: paths.auth.signIn })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Password reset failed.')
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthFrame>
      <section className="fs-card fs-auth-card" aria-label="Reset password">
        <div className="fs-auth-head">
          <h1>Reset password</h1>
          <p>Enter your new password below.</p>
        </div>

        <form onSubmit={(e) => void onSubmit(e)} className="fs-auth-form">
          {email && (
            <div className="fs-field">
              <label className="fs-label" htmlFor="email">
                Email
              </label>
              <input className="fs-input" id="email" type="email" value={email} disabled />
            </div>
          )}
          <div className="fs-field">
            <label className="fs-label" htmlFor="password">
              New password
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
            {pending ? 'Resetting…' : 'Reset password'}
          </button>
        </form>

        <div className="fs-auth-links">
          <span>
            <Link to={paths.auth.signIn}>Back to Sign in</Link>
          </span>
        </div>
      </section>
    </AuthFrame>
  )
}
