/**
 * Confirm email page.
 *
 * Calls POST /auth/email/confirm (items 3+4): the backend verifies the token AND
 * sets the session cookie, so the user is auto-logged-in. On success we refresh
 * the current-user query and send the user straight to the dashboard — no second
 * sign-in step.
 *
 * Already-verified links (409) route to sign-in; invalid/expired links (400) show
 * the error page.
 */
import React, { useEffect, useState } from 'react'
import { Link, useSearch, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'

import { Spinner } from '@/shared/components/spinner'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { CURRENT_USER_QUERY_KEY } from '@/entities/viewer/model'
import { AuthFrame } from './auth-frame'

const REDIRECT_DELAY_MS = 1200

export const ConfirmEmailPage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string; email?: string }
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { token, email } = search

  const [status, setStatus] = useState<'pending' | 'done' | 'error'>('pending')

  useEffect(() => {
    if (!token || !email) return
    let cancelled = false
    apiClient
      .post('/auth/email/confirm', { token })
      .then(async () => {
        if (cancelled) return
        // Cookie is set → refresh auth state, then land on the dashboard.
        await queryClient.invalidateQueries({ queryKey: CURRENT_USER_QUERY_KEY })
        setStatus('done')
        setTimeout(() => {
          if (!cancelled) void navigate({ to: paths.home, replace: true })
        }, REDIRECT_DELAY_MS)
      })
      .catch((err: AxiosError) => {
        if (cancelled) return
        // Already verified → not an error; just send them to sign in.
        if (err.response?.status === 409) {
          void navigate({ to: paths.auth.signIn, replace: true })
          return
        }
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [token, email, navigate, queryClient])

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
                Your email is confirmed and you&apos;re signed in. Taking you to your dashboard.
              </p>
            </div>

            <Link to={paths.home} className="fs-btn fs-btn--primary fs-btn--block">
              Go to dashboard
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
