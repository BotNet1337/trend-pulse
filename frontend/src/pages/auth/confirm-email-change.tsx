/**
 * Confirm email change page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'

import { Spinner } from '@/shared/components/spinner'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { BRAND_NAME } from '@/shared/config'

export const ConfirmEmailChangePage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string }
  const navigate = useNavigate()
  const calledRef = useRef(false)
  const { token } = search

  const [status, setStatus] = useState<'pending' | 'done' | 'error'>('pending')

  useEffect(() => {
    if (!token || calledRef.current) return
    calledRef.current = true
    apiClient
      .post('/auth/email/confirm-change', { token })
      .then(() => {
        setStatus('done')
        setTimeout(() => { void navigate({ to: paths.auth.signIn }) }, 2000)
      })
      .catch(() => setStatus('error'))
  }, [token, navigate])

  if (!token) {
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
            {status === 'pending' ? 'Updating your email…' : 'Email updated! Redirecting to sign in…'}
          </p>
        </div>
      </div>
    </div>
  )
}
