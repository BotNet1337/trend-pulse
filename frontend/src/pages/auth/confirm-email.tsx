/**
 * Confirm email page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useEffect, useState } from 'react'
import { Link, useSearch, useNavigate } from '@tanstack/react-router'

import { Spinner } from '@/shared/components/spinner'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { AuthFrame } from './auth-frame'

export const ConfirmEmailPage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string; email?: string }
  const navigate = useNavigate()
  const { token, email } = search

  const [status, setStatus] = useState<'pending' | 'done' | 'error'>('pending')

  useEffect(() => {
    if (!token || !email) return
    apiClient
      .post('/auth/verify', { token })
      .then(() => {
        setStatus('done')
        setTimeout(() => { void navigate({ to: paths.auth.signIn }) }, 2000)
      })
      .catch(() => setStatus('error'))
  }, [token, email, navigate])

  if (!token || !email) {
    return <SomethingWentWrongPage />
  }

  if (status === 'error') {
    return <SomethingWentWrongPage />
  }

  return (
    <AuthFrame>
      <section className="fs-card fs-auth-card fs-auth-card--center" aria-label="Email confirmation">
        {status === 'done' ? (
          <>
            <div className="fs-confirm-icon" aria-hidden="true">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>

            <div role="status" aria-live="polite">
              <p className="fs-confirm-status">Email verified! Redirecting…</p>
              <p className="fs-confirm-sub">
                Your email address has been confirmed. You can now sign in to your account.
              </p>
            </div>

            <Link to={paths.auth.signIn} className="fs-btn fs-btn--primary fs-btn--block">
              Continue to sign in
            </Link>
          </>
        ) : (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col items-center justify-center gap-4 py-8"
          >
            <Spinner className="size-8" />
            <p className="fs-confirm-sub animate-pulse">Verifying your email…</p>
          </div>
        )}
      </section>
    </AuthFrame>
  )
}
