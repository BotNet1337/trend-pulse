/**
 * Forgot password page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useState } from 'react'
import { Link } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { AuthFrame } from './auth-frame'

export const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await apiClient.post('/auth/forgot-password', { email })
      setSent(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to send reset email.')
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthFrame>
      <section className="fs-card fs-auth-card" aria-label="Forgot password">
        <div className="fs-auth-head">
          <h1>Forgot password</h1>
          <p>Enter your email and we&apos;ll send you a reset link</p>
        </div>

        {sent ? (
          <div className="fs-banner fs-banner--info" role="status" style={{ textAlign: 'center' }}>
            Check your email for a password reset link.
          </div>
        ) : (
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

            {error && (
              <p className="fs-error" role="alert">
                {error}
              </p>
            )}

            <button
              type="submit"
              className="fs-btn fs-btn--primary fs-btn--block"
              disabled={pending}
            >
              {pending ? 'Sending…' : 'Send reset link'}
            </button>
          </form>
        )}

        <div className="fs-auth-links">
          <span>
            Remember your password? <Link to={paths.auth.signIn}>Sign in</Link>
          </span>
        </div>
      </section>
    </AuthFrame>
  )
}
