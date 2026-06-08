import React, { useEffect } from 'react'
import { useSearch, useNavigate } from '@tanstack/react-router'

import { Spinner } from '@/shared/components/spinner'
import { AUTH_HERO, AuthShell, useConfirmEmail } from '@/features'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from "@/app/router/path"

export const ConfirmEmailPage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string; email?: string }
  const navigate = useNavigate()
  const { mutate: confirmEmail, isPending, isError } = useConfirmEmail({
    onSuccess: async () => {
      setTimeout(() => {
        navigate({ to: paths.auth.signIn })
      }, 2000)
    }
  })

  const { token, email } = search

  useEffect(() => {
    if (token && email) {
      confirmEmail({ token, email })
    }
  }, [token, email, confirmEmail])

  if (!token || !email) {
    return <SomethingWentWrongPage />
  }

  if (isError) {
    return <SomethingWentWrongPage />
  }

  return (
    <AuthShell hero={AUTH_HERO.confirm}>
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center justify-center gap-4 py-12 text-muted-foreground text-sm"
      >
        <Spinner className="size-8 text-brand" />
        <p className="animate-pulse m-0">
          {isPending ? "Verifying your email..." : "Email verified! Redirecting..."}
        </p>
      </div>
    </AuthShell>
  )
}
