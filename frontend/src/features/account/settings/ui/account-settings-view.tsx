import * as React from "react"

import { useAuth } from "@/app/providers/use-auth"
import { Button } from "@/shared/components/button"
import { DeleteAccountDialog } from "../../delete/ui/delete-account-dialog"
import { ChangePasswordDialog } from "../../password/ui/change-password-dialog"
import { ChangeEmailDialog } from "../../email/ui/change-email-dialog"

export const AccountSettingsView: React.FC = () => {
  const authStore = useAuth()
  const user = authStore((state) => state.user)
  const userId = user?.userId ?? ""
  const email = user?.email ?? ""
  const provider = user?.provider ?? "email"

  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [changePasswordOpen, setChangePasswordOpen] = React.useState(false)
  const [changeEmailOpen, setChangeEmailOpen] = React.useState(false)

  const displayName = email.split("@")[0] || "Your account"

  const initialsOf = (label: string): string => {
    const cleaned = label.trim()
    if (!cleaned) return "U"
    const parts = cleaned.split(/[\s@._-]+/g).filter(Boolean)
    return ((parts[0]?.[0] ?? "U") + (parts[1]?.[0] ?? "")).toUpperCase()
  }

  return (
    <div
      data-testid="account-settings-page"
      className="mx-auto flex w-full max-w-[860px] flex-col gap-8 px-8 py-8"
    >
      <header className="flex flex-col gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-medium">
          Account
        </span>
        <h1 className="m-0 text-2xl font-bold tracking-[-0.01em]">
          Account settings
        </h1>
        <p className="m-0 text-sm text-muted-foreground">
          Manage your TrendPulse account.
        </p>
      </header>

      <section className="rounded-2xl border border-border bg-background p-6">
        <header className="mb-5 flex flex-col gap-1">
          <h3 className="m-0 text-base font-semibold">Profile</h3>
        </header>

        <div className="flex items-center gap-4 border-b border-border pb-5">
          <span className="inline-flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-violet-700 text-xl font-bold text-white">
            {initialsOf(displayName)}
          </span>
          <div className="flex flex-1 flex-col gap-0.5">
            <span className="text-base font-semibold">{displayName}</span>
            <span className="text-sm text-muted-foreground">{email}</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.05em] text-muted-foreground">
              Signed in via {provider}
            </span>
          </div>
        </div>

        <div
          data-testid="account-settings-email"
          className="mt-5 grid grid-cols-1 items-start gap-3 md:grid-cols-[1fr_320px]"
        >
          <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Email</span>
            <span className="text-xs text-muted-foreground">
              Used for sign-in and notifications.
            </span>
          </div>
          <div className="grid grid-cols-[1fr_auto] items-center gap-2">
            <div className="flex h-10 min-w-0 items-center rounded-md border border-border bg-secondary/40 px-3 text-sm text-foreground">
              <span className="truncate">{email || "—"}</span>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="min-w-20"
              onClick={() => setChangeEmailOpen(true)}
              data-testid="account-settings-email-change"
              disabled={!userId}
            >
              Change
            </Button>
          </div>
        </div>

        <div
          data-testid="account-settings-password"
          className="mt-5 grid grid-cols-1 items-start gap-3 border-t border-border pt-5 md:grid-cols-[1fr_320px]"
        >
          <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Password</span>
            <span className="text-xs text-muted-foreground">
              Change your password to keep your account secure.
            </span>
          </div>
          <div className="grid grid-cols-[1fr_auto] items-center gap-2">
            <div className="flex h-10 min-w-0 items-center rounded-md border border-border bg-secondary/40 px-3 text-sm text-foreground">
              <span aria-hidden="true">••••••••</span>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="min-w-20"
              onClick={() => setChangePasswordOpen(true)}
              data-testid="account-settings-password-change"
              disabled={!userId}
            >
              Change
            </Button>
          </div>
        </div>
      </section>

      <section
        data-testid="account-danger-zone"
        className="rounded-2xl border border-destructive/30 bg-destructive/[0.02] p-6"
      >
        <header className="mb-5 flex flex-col gap-1">
          <h3 className="m-0 text-base font-semibold">Danger zone</h3>
          <p className="m-0 text-xs text-muted-foreground">
            Permanent actions on your account.
          </p>
        </header>

        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Delete account</span>
            <span className="text-xs text-muted-foreground">
              Removes your account and all your data. This cannot be undone.
            </span>
          </div>
          <Button
            type="button"
            variant="destructive"
            data-testid="account-settings-delete"
            onClick={() => setDeleteOpen(true)}
            disabled={!userId}
          >
            Delete account
          </Button>
        </div>
      </section>

      <DeleteAccountDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        userId={userId}
        email={email}
        ownedWorkspacesCount={0}
        ownedPostsCount={0}
      />

      <ChangePasswordDialog
        open={changePasswordOpen}
        onOpenChange={setChangePasswordOpen}
      />

      <ChangeEmailDialog
        open={changeEmailOpen}
        onOpenChange={setChangeEmailOpen}
        currentEmail={email}
      />
    </div>
  )
}
