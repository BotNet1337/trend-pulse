import * as React from "react"

import { useAuth } from "@/app/providers/use-auth"
import { useCurrentUser } from "@/entities/viewer/model"
import { type PlanId, PLAN_FREE } from "@/entities/plan"
import { Button } from "@/shared/components/button"
import { BRAND_NAME, SUPPORT_EMAIL } from "@/shared/config"
import { DeliveryConfigForm } from "@/features/delivery-config/ui/delivery-config-form"
import { useDeliveryConfig, useUpdateDeliveryConfig } from "@/features/delivery-config/model"
import { ApiKeysSection } from "@/features/api-keys"
import { DeleteAccountDialog } from "../../delete/ui/delete-account-dialog"
import { ChangePasswordDialog } from "../../password/ui/change-password-dialog"
import { ChangeEmailDialog } from "../../email/ui/change-email-dialog"

export const AccountSettingsView: React.FC = () => {
  const authStore = useAuth()
  const user = authStore((state) => state.user)
  const userId = user?.userId ?? ""
  const email = user?.email ?? ""
  const provider = user?.provider ?? "email"

  const { data: currentUser } = useCurrentUser()
  const currentPlan = (currentUser?.plan ?? PLAN_FREE) as PlanId

  const { data: deliveryConfig } = useDeliveryConfig()
  const updateDeliveryMutation = useUpdateDeliveryConfig()

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
    <div data-testid="account-settings-page" className="fs-container">
      <div className="fs-page-head">
        <h1 className="fs-page-head__title">Account settings</h1>
        <p className="fs-page-head__sub">Manage your {BRAND_NAME} account.</p>
      </div>

      <div className="settings-stack">
        <section className="fs-card fs-form-section" aria-labelledby="profile-heading">
          <header className="fs-form-section__head">
            <h2 id="profile-heading" className="fs-form-section__title">Profile</h2>
          </header>

          <div className="fs-form-section__body">
            <div className="profile-row">
              <span className="profile-row__avatar" aria-hidden="true">
                {initialsOf(displayName)}
              </span>
              <div className="profile-row__main">
                <span className="profile-row__name">{displayName}</span>
                <span className="fs-muted" style={{ fontSize: "0.88rem" }}>{email}</span>
                <span className="profile-row__via">Signed in via {provider}</span>
              </div>
            </div>

            <div data-testid="account-settings-email" className="setting-row">
              <div className="setting-row__main">
                <span className="fs-label">Email</span>
                <p className="fs-hint">Used for sign-in and notifications.</p>
              </div>
              <span className="setting-row__value" title={email}>{email || "—"}</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setChangeEmailOpen(true)}
                data-testid="account-settings-email-change"
                disabled={!userId}
              >
                Change
              </Button>
            </div>

            <hr className="fs-divider" style={{ margin: "0.25rem 0" }} />

            <div data-testid="account-settings-password" className="setting-row">
              <div className="setting-row__main">
                <span className="fs-label">Password</span>
                <p className="fs-hint">Change your password to keep your account secure.</p>
              </div>
              <span className="setting-row__value" aria-hidden="true">••••••••</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setChangePasswordOpen(true)}
                data-testid="account-settings-password-change"
                disabled={!userId}
              >
                Change
              </Button>
            </div>
          </div>
        </section>

        {/* Delivery configuration — Telegram + webhook (TASK-017 AC2/AC3/AC4/AC5) */}
        <section
          data-testid="delivery-config-section"
          className="fs-card fs-form-section"
          aria-labelledby="delivery-heading"
        >
          <header className="fs-form-section__head">
            <h2 id="delivery-heading" className="fs-form-section__title">Notification delivery</h2>
            <p className="fs-form-section__desc">
              Configure how {BRAND_NAME} delivers alerts to you.
            </p>
          </header>

          {deliveryConfig ? (
            <DeliveryConfigForm
              current={deliveryConfig}
              currentPlan={currentPlan}
              isSaving={updateDeliveryMutation.isPending}
              onSave={async (data) => {
                await updateDeliveryMutation.mutateAsync(data)
              }}
            />
          ) : (
            <div className="fs-muted" style={{ padding: "1rem 0" }}>Loading delivery settings…</div>
          )}
        </section>

        {/* API keys — issue / copy-once / revoke (TASK-065; Trader/Team gate) */}
        <ApiKeysSection currentPlan={currentPlan} />

        <section
          data-testid="account-support"
          className="fs-card fs-form-section"
          aria-labelledby="support-heading"
        >
          <header className="fs-form-section__head" style={{ marginBottom: "0.4rem" }}>
            <h2 id="support-heading" className="fs-form-section__title">Help &amp; support</h2>
          </header>
          <p className="fs-muted" style={{ margin: 0, fontSize: "0.9rem" }}>
            Need help?{" "}
            <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>
          </p>
        </section>

        <section
          data-testid="account-danger-zone"
          className="fs-card fs-form-section danger-zone"
          aria-labelledby="danger-heading"
        >
          <header className="fs-form-section__head">
            <h2 id="danger-heading" className="fs-form-section__title">Danger zone</h2>
            <p className="fs-form-section__desc">Permanent actions on your account.</p>
          </header>

          <div className="setting-row">
            <div className="setting-row__main">
              <span className="fs-label">Delete account</span>
              <p className="fs-hint">Removes your account and all your data. This cannot be undone.</p>
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
      </div>

      <DeleteAccountDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        userId={userId}
        email={email}
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
