import * as React from "react"
import { useNavigate } from "@tanstack/react-router"

import { Button } from "@/shared/components/button"
import { Input } from "@/shared/components/input"
import { useAuth } from "@/app/providers/use-auth"
import { paths } from "@/app/router/path"
import { useWorkspaces } from "@/features/workspaces/list"
import { SettingsTabs } from "@/features/workspaces/settings/ui/settings-tabs"

import { PatSection } from "@/features/pat/ui/pat-section"

import { useMe, useUpdateUserProfile } from "../../profile"
import { DeleteAccountDialog } from "../../delete/ui/delete-account-dialog"
import { ChangePasswordDialog } from "../../password/ui/change-password-dialog"
import { ChangeEmailDialog } from "../../email/ui/change-email-dialog"

const initialsOf = (label: string): string => {
  const cleaned = label.trim()
  if (!cleaned) return "U"
  const parts = cleaned.split(/[\s@._-]+/g).filter(Boolean)
  return ((parts[0]?.[0] ?? "U") + (parts[1]?.[0] ?? "")).toUpperCase()
}

export const AccountSettingsView: React.FC = () => {
  const navigate = useNavigate()
  const authStore = useAuth()
  const user = authStore((state) => state.user)
  const userId = user?.userId ?? ""
  const email = user?.email ?? ""
  const provider = user?.provider ?? "email"

  const meQuery = useMe()
  const workspacesQuery = useWorkspaces({ limit: 100 })
  const updateProfile = useUpdateUserProfile()

  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [changePasswordOpen, setChangePasswordOpen] = React.useState(false)
  const [changeEmailOpen, setChangeEmailOpen] = React.useState(false)
  const [nameDraft, setNameDraft] = React.useState<string>("")
  const [editingName, setEditingName] = React.useState(false)

  React.useEffect(() => {
    if (!editingName) {
      setNameDraft(meQuery.data?.name ?? "")
    }
  }, [meQuery.data?.name, editingName])

  const submitName = async (): Promise<void> => {
    const trimmed = nameDraft.trim()
    if (!trimmed || trimmed === (meQuery.data?.name ?? "")) {
      setEditingName(false)
      return
    }
    try {
      await updateProfile.mutateAsync({ userId, name: trimmed })
      setEditingName(false)
    } catch {
      // alert is handled inside the mutation hook
    }
  }

  const ownedWorkspaces = (workspacesQuery.data?.data ?? []).filter(
    (workspace) => workspace.authorId === userId,
  )
  const ownedWorkspacesCount = ownedWorkspaces.length
  const ownedPostsCount = ownedWorkspaces.reduce(
    (sum, workspace) => sum + (workspace.postsCount ?? 0),
    0,
  )

  const displayName =
    meQuery.data?.name?.trim() || email.split("@")[0] || "Your account"
  const avatarUrl = meQuery.data?.avatar?.url ?? null

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
          Visible across every workspace you belong to.
        </p>
      </header>

      <SettingsTabs
        active="account"
        hideWorkspace
        onAccountClick={undefined}
        onWorkspaceClick={() => {
          if (ownedWorkspaces[0]) {
            void navigate({
              to: paths.workspaces.settings(ownedWorkspaces[0].id),
            })
          }
        }}
      />

      <section className="rounded-2xl border border-border bg-background p-6">
        <header className="mb-5 flex flex-col gap-1">
          <h3 className="m-0 text-base font-semibold">Profile</h3>
          <p className="m-0 text-xs text-muted-foreground">
            Visible across every workspace you belong to.
          </p>
        </header>

        <div className="flex items-center gap-4 border-b border-border pb-5">
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt=""
              className="h-16 w-16 shrink-0 rounded-full object-cover"
            />
          ) : (
            <span className="inline-flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-rose-400 to-rose-700 text-xl font-bold text-white">
              {initialsOf(displayName)}
            </span>
          )}
          <div className="flex flex-1 flex-col gap-0.5">
            <span className="text-base font-semibold">{displayName}</span>
            <span className="text-sm text-muted-foreground">{email}</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.05em] text-muted-foreground">
              Signed in via {provider}
            </span>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-1 items-start gap-3 border-b border-border pb-5 md:grid-cols-[1fr_320px]">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Display name</span>
            <span className="text-xs text-muted-foreground">
              Shown to teammates in comments, mentions and activity logs.
            </span>
          </div>
          {editingName ? (
            <div className="flex flex-col gap-2">
              <Input
                value={nameDraft}
                onChange={(event) => setNameDraft(event.target.value)}
                placeholder="Your name"
                maxLength={80}
                autoFocus
                data-testid="account-settings-name-input"
              />
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void submitName()}
                  disabled={updateProfile.isPending || nameDraft.trim().length === 0}
                  data-testid="account-settings-name-save"
                >
                  {updateProfile.isPending ? "Saving…" : "Save"}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditingName(false)
                    setNameDraft(meQuery.data?.name ?? "")
                  }}
                  disabled={updateProfile.isPending}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-[1fr_auto] items-center gap-2">
              <div className="flex h-10 min-w-0 items-center rounded-md border border-border bg-secondary/40 px-3 text-sm text-foreground">
                <span className="truncate">{displayName}</span>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="min-w-20"
                onClick={() => setEditingName(true)}
                data-testid="account-settings-name-edit"
                disabled={!userId}
              >
                Edit
              </Button>
            </div>
          )}
        </div>

        <div
          data-testid="account-settings-email"
          className="mt-5 grid grid-cols-1 items-start gap-3 md:grid-cols-[1fr_320px]"
        >
          <div className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Email</span>
            <span className="text-xs text-muted-foreground">
              Used for sign-in and notifications. Changing requires
              re-confirmation via the new address.
            </span>
          </div>
          <div className="grid grid-cols-[1fr_auto] items-center gap-2">
            <div className="flex h-10 min-w-0 items-center rounded-md border border-border bg-secondary/40 px-3 text-sm text-foreground">
              <span className="truncate">{email || "—"}</span>
            </div>
            {meQuery.data?.hasPassword ? (
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
            ) : (
              <div aria-hidden="true" className="w-20" />
            )}
          </div>
        </div>

        {meQuery.data?.hasPassword ? (
          <div
            data-testid="account-settings-password"
            className="mt-5 grid grid-cols-1 items-start gap-3 border-t border-border pt-5 md:grid-cols-[1fr_320px]"
          >
            <div className="flex flex-col gap-1">
              <span className="text-sm font-semibold">Password</span>
              <span className="text-xs text-muted-foreground">
                Change your password regularly to keep your account secure.
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
        ) : null}
      </section>

      <PatSection workspaceId={ownedWorkspaces[0]?.id ?? ""} />

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
              Removes your account, <b>{ownedWorkspacesCount}</b>{" "}
              {ownedWorkspacesCount === 1 ? "workspace" : "workspaces"} you own
              and <b>{ownedPostsCount}</b>{" "}
              {ownedPostsCount === 1 ? "post" : "posts"}. Workspaces you've
              been invited to will continue without you. This cannot be undone.
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
        ownedWorkspacesCount={ownedWorkspacesCount}
        ownedPostsCount={ownedPostsCount}
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
