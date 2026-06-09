/**
 * Forgot password page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useState } from 'react'
import { Link } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { apiClient } from '@/shared/api'
import { Button } from '@/shared/components/button'
import { Input } from '@/shared/components/input'
import { Label } from '@/shared/components/label'
import { BRAND_NAME } from '@/shared/config'

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
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col gap-2 text-center">
          <h1 className="text-2xl font-bold tracking-tight">{BRAND_NAME}</h1>
          <h2 className="text-lg font-semibold">Forgot password</h2>
          <p className="text-sm text-muted-foreground">
            Enter your email and we&apos;ll send you a reset link
          </p>
        </div>

        {sent ? (
          <div className="rounded-lg border border-border bg-secondary/20 p-4 text-sm text-center text-muted-foreground">
            Check your email for a password reset link.
          </div>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
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
              <p className="text-sm text-destructive" role="alert">{error}</p>
            )}

            <Button type="submit" disabled={pending} className="w-full">
              {pending ? 'Sending…' : 'Send reset link'}
            </Button>
          </form>
        )}

        <div className="text-center text-sm text-muted-foreground">
          Remember your password?{' '}
          <Link to={paths.auth.signIn} className="text-foreground underline underline-offset-2">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
