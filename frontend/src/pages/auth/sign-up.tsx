/**
 * Sign-up page — TASK-014 (C2) implementation.
 *
 * Endpoint: POST /auth/register JSON { email, password }
 * On success: redirect to /auth/sign-in so user can log in (register does NOT
 * auto-login — fastapi-users returns UserRead, not a cookie).
 * On duplicate email: backend returns 400; shown as friendly error (no enumeration).
 */
import React, { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'

import { paths } from '@/app/router/path'
import { Button } from '@/shared/components/button'
import { Input } from '@/shared/components/input'
import { Label } from '@/shared/components/label'
import { BRAND_NAME } from '@/shared/config'
import { register } from '@/features/auth'

export const SignUpPage: React.FC = () => {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const registerMutation = useMutation({
    mutationFn: () => register({ email, password }),
  })

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await registerMutation.mutateAsync()
      await navigate({ to: paths.auth.signIn, replace: true })
    } catch (err: unknown) {
      // Friendly message — do not reveal whether email already exists (AC5/no-enumeration)
      setError(err instanceof Error ? err.message : 'Registration failed. Please try again.')
    }
  }

  const pending = registerMutation.isPending

  return (
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col gap-2 text-center">
          <h1 className="text-2xl font-bold tracking-tight">{BRAND_NAME}</h1>
          <h2 className="text-lg font-semibold">Create your account</h2>
          <p className="text-sm text-muted-foreground">
            Start tracking viral content from Telegram
          </p>
        </div>

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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
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
            {pending ? 'Creating account…' : 'Create account'}
          </Button>
        </form>

        <div className="text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link to={paths.auth.signIn} className="text-foreground underline underline-offset-2">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
