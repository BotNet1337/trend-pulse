/**
 * Confirm email page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useEffect, useState } from 'react'
import { useSearch, useNavigate } from '@tanstack/react-router'

import { Spinner } from '@/shared/components/spinner'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { BRAND_NAME } from '@/shared/config'

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
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-4">
      <div className="w-full max-w-sm flex flex-col gap-6 items-center text-center">
        <h1 className="text-2xl font-bold tracking-tight">{BRAND_NAME}</h1>
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center justify-center gap-4 py-8 text-muted-foreground text-sm"
        >
          <Spinner className="size-8" />
          <p className="animate-pulse m-0">
            {status === 'pending' ? 'Verifying your email…' : 'Email verified! Redirecting…'}
          </p>
        </div>
      </div>
    </div>
  )
}
