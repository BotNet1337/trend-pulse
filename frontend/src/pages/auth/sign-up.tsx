import React from 'react'
import { Link } from '@tanstack/react-router'

import { paths } from "@/app/router/path"
import { AUTH_HERO, AuthShell, SignUpFlow } from '@/features'

export const SignUpPage: React.FC = () => {
  return (
    <AuthShell hero={AUTH_HERO.signUp}>
      <SignUpFlow />

      <div className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
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
