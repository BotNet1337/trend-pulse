import * as React from "react"

import { AccountSettingsView } from "@/features/account"
import { BRAND_NAME } from "@/shared/config"

export const AccountSettingsPage: React.FC = () => {
  return (
    <div className="auth-light h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <header className="border-b border-border px-8 py-3 flex items-center gap-3">
        <span className="font-semibold text-sm">{BRAND_NAME}</span>
      </header>
      <main className="flex-1 min-w-0 bg-background overflow-y-auto">
        <AccountSettingsView />
      </main>
    </div>
  )
}
