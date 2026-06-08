import React, { useEffect, useRef } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'

import { Spinner } from '@/shared/components/spinner'
import { AUTH_HERO, AuthShell } from '@/features'
import { useConfirmEmailChange } from '@/features/account/email'
import { SomethingWentWrongPage } from '@/pages/error/something-went-wrong'
import { paths } from '@/app/router/path'

export const ConfirmEmailChangePage: React.FC = () => {
  const search = useSearch({ strict: false }) as { token?: string }
  const navigate = useNavigate()
  const calledRef = useRef(false)

  const {
    mutate: confirmEmailChange,
    isPending,
    isError,
    isSuccess,
  } = useConfirmEmailChange({
    onSuccess: async () => {
      setTimeout(() => {
        void navigate({ to: paths.auth.signIn })
      }, 2000)
    },
  })

  const { token } = search

  useEffect(() => {
    if (token && !calledRef.current) {
      calledRef.current = true
      confirmEmailChange({ token })
    }
  }, [token, confirmEmailChange])

  if (!token) {
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
          {isPending && 'Updating your email...'}
          {isSuccess && 'Email updated! Redirecting to sign in...'}
          {!isPending && !isSuccess && 'Verifying token...'}
        </p>
      </div>
    </AuthShell>
  )
}
