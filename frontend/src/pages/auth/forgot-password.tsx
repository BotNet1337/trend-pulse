import React from 'react'
import { Link } from '@tanstack/react-router'

import { paths } from "@/app/router/path"
import { AUTH_HERO, AuthShell, ForgotPasswordFlow } from '@/features'

export const ForgotPasswordPage: React.FC = () => {
  return (
    <AuthShell hero={AUTH_HERO.forgot}>
      <ForgotPasswordFlow />

      <div className="text-center text-sm text-muted-foreground">
        Remember your password?{" "}
        <Link
          to={paths.auth.signIn}
          className="text-foreground underline underline-offset-[3px] hover:text-brand"
        >
          Sign in
        </Link>
      </div>
    </AuthShell>
  )
}
