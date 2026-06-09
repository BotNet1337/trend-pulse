import * as React from "react"

import { AccountSettingsView } from "@/features/account"
import { useLogout } from "@/features/auth"
import { Button } from "@/shared/components/button"
import { BRAND_NAME } from "@/shared/config"

export const AccountSettingsPage: React.FC = () => {
  const logoutMutation = useLogout()

  return (
    <div className="auth-light h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <header className="border-b border-border px-8 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm flex-1">{BRAND_NAME}</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={logoutMutation.isPending}
          onClick={() => logoutMutation.mutate()}
          aria-label="Sign out"
        >
          {logoutMutation.isPending ? 'Signing out…' : 'Sign out'}
        </Button>
      </header>
      <main className="flex-1 min-w-0 bg-background overflow-y-auto">
        <AccountSettingsView />
      </main>
    </div>
  )
}
