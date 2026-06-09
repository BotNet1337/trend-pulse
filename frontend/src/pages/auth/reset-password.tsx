/**
 * Reset password page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useState } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { Button } from '@/shared/components/button'
import { Input } from '@/shared/components/input'
import { Label } from '@/shared/components/label'
import { BRAND_NAME } from '@/shared/config'
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
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col gap-2 text-center">
          <h1 className="text-2xl font-bold tracking-tight">{BRAND_NAME}</h1>
          <h2 className="text-lg font-semibold">Reset password</h2>
          <p className="text-sm text-muted-foreground">
            Enter your new password below.
          </p>
        </div>

        <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
          {email && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} disabled />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">New password</Label>
            <Input
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
            <p className="text-sm text-destructive" role="alert">{error}</p>
          )}

          <Button type="submit" disabled={pending} className="w-full">
            {pending ? 'Resetting…' : 'Reset password'}
          </Button>
        </form>

        <div className="text-center text-sm text-muted-foreground">
          <Link to={paths.auth.signIn} className="text-foreground underline underline-offset-2">
            Back to Sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
