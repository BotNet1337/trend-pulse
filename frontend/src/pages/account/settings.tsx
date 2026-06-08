import * as React from "react"

import { AccountSettingsView } from "@/features/account"
import { WorkspaceTopBar } from "@/features/workspaces"

export const AccountSettingsPage: React.FC = () => {
  return (
    <div className="auth-light h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <WorkspaceTopBar />
      <main className="flex-1 min-w-0 bg-background overflow-y-auto">
        <AccountSettingsView />
      </main>
    </div>
  )
}
