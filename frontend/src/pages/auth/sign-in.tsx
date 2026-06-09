/**
 * Sign-in page — TrendPulse C1 foundation placeholder.
 * Full auth flow implementation: task-014.
 */
import React, { useState } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'

import { paths } from '@/app/router/path'
import { apiClient, isSafeRedirect } from '@/shared/api'
import { Button } from '@/shared/components/button'
import { Input } from '@/shared/components/input'
import { Label } from '@/shared/components/label'
import { BRAND_NAME } from '@/shared/config'

export const SignInPage: React.FC = () => {
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as { redirect?: string }

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      const form = new URLSearchParams()
      form.set('username', email)
      form.set('password', password)
      await apiClient.post('/auth/jwt/login', form, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
      // Harden against open-redirect: only honour internal same-origin paths
      // from the attacker-controllable `?redirect=` param (A01 / unvalidated redirect).
      const redirectTo =
        search.redirect && isSafeRedirect(search.redirect) ? search.redirect : paths.home
      await navigate({ to: redirectTo, replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col gap-2 text-center">
          <h1 className="text-2xl font-bold tracking-tight">{BRAND_NAME}</h1>
          <h2 className="text-lg font-semibold">Welcome back</h2>
          <p className="text-sm text-muted-foreground">
            Enter your credentials to sign in to your account
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={pending}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-sm text-destructive" role="alert">{error}</p>
          )}

          <Button type="submit" disabled={pending} className="w-full">
            {pending ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <div className="text-center text-sm text-muted-foreground flex flex-col gap-1">
          <Link to={paths.auth.forgotPassword} className="underline underline-offset-2 hover:text-foreground">
            Forgot password?
          </Link>
          <span>
            Don&apos;t have an account?{' '}
            <Link to={paths.auth.signUp} className="text-foreground underline underline-offset-2">
              Sign up
            </Link>
          </span>
        </div>
      </div>
    </div>
  )
}
