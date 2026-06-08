import type React from "react"
import { Link, useNavigate } from "@tanstack/react-router"

import { paths } from "@/app/router/path"
import { AUTH_HERO, AuthShell, SignInForm } from "@/features"

export const SignInPage: React.FC = () => {
  const navigate = useNavigate()

  const onSuccess = async () => {
    await navigate({ to: paths.workspaces.list, replace: true })
  }

  return (
    <AuthShell hero={AUTH_HERO.signIn}>
      <div className="flex flex-col gap-2">
        <h2 className="m-0 font-bold text-2xl leading-[1.2] tracking-[-0.02em]">
          Welcome back
        </h2>
        <p className="m-0 text-sm text-muted-foreground leading-[1.5]">
          Enter your credentials to sign in to your account
        </p>
      </div>

      <SignInForm onSuccess={onSuccess} />

      <div className="text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link
          to={paths.auth.signUp}
          className="text-foreground underline underline-offset-[3px] hover:text-brand"
        >
          Sign up
        </Link>
      </div>
    </AuthShell>
  )
}
