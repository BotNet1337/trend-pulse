import React from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'

import { paths } from "@/app/router/path"
import { AUTH_HERO, AuthShell, ResetPasswordForm } from '@/features'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'

export const ResetPasswordPage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string; email?: string }

  const navigate = useNavigate()

  const { token, email } = search

  if (!token) {
    return <SomethingWentWrongPage />
  }

  const onSuccess = async () => {
    await navigate({ to: paths.auth.signIn })
  }

  return (
    <AuthShell hero={AUTH_HERO.reset}>
      <div className="flex flex-col gap-2">
        <h2 className="m-0 font-bold text-2xl leading-[1.2] tracking-[-0.02em]">
          Reset password
        </h2>
        <p className="m-0 text-sm text-muted-foreground leading-[1.5]">
          Enter your new password below.
        </p>
      </div>

      <ResetPasswordForm
        token={token}
        defaultValues={{ email: email || "", password: "", confirmPassword: "" }}
        onSuccess={onSuccess}
      />

      <div className="text-center text-sm text-muted-foreground">
        <Link
          to={paths.auth.signIn}
          className="text-foreground underline underline-offset-[3px] hover:text-brand"
        >
          Back to Sign in
        </Link>
      </div>
    </AuthShell>
  )
}
