import * as React from "react"

import { Link } from "@tanstack/react-router"

import { paths } from "@/app/router/path"
import { isPlanAtLeast, PLAN_DISPLAY_NAME, PLAN_TEAM, type PlanId } from "@/entities/plan"
import { Button } from "@/shared/components/button"
import { Input } from "@/shared/components/input"
import { Label } from "@/shared/components/label"
import { Spinner } from "@/shared/components/spinner"
import { BRAND_NAME } from "@/shared/config"
import { KeyRound } from "@/shared/images"

import type { ApiKeyCreated, ApiKeyRead } from "../api"
import { extractApiKeysErrorMessage } from "../error-message"
import { API_KEY_NAME_MAX_LEN, formatApiKeyDate, isApiKeyRevoked, validateApiKeyName } from "../lib"
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "../queries"
import { CreatedKeyModal } from "./created-key-modal"
import { RevokeKeyDialog } from "./revoke-key-dialog"

export interface ApiKeysSectionProps {
  currentPlan: PlanId
}

const TRADER_NAME = PLAN_DISPLAY_NAME[PLAN_TEAM]

/**
 * "API keys" section in account settings (TASK-065).
 *
 * Trader/Team: list + create (one-time plaintext modal) + revoke with confirm.
 * Free/Pro: upgrade CTA → /billing (UX layer only — the real gate is the
 * backend 403 on POST /api-keys).
 *
 * INVARIANT: the plaintext key lives only in `createdKey` local state while the
 * modal is open; the mutation state is reset right after so no copy lingers.
 */
export const ApiKeysSection: React.FC<ApiKeysSectionProps> = ({ currentPlan }) => {
  const hasApiAccess = isPlanAtLeast(currentPlan, PLAN_TEAM)

  const keysQuery = useApiKeys({ enabled: hasApiAccess })
  const createMutation = useCreateApiKey()
  const revokeMutation = useRevokeApiKey()

  const [name, setName] = React.useState("")
  const [nameError, setNameError] = React.useState<string | null>(null)
  const [createError, setCreateError] = React.useState<string | null>(null)
  const [createdKey, setCreatedKey] = React.useState<ApiKeyCreated | null>(null)
  const [revokeTarget, setRevokeTarget] = React.useState<ApiKeyRead | null>(null)
  const [revokeError, setRevokeError] = React.useState<string | null>(null)

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    const validationError = validateApiKeyName(name)
    setNameError(validationError)
    if (validationError || createMutation.isPending) return

    setCreateError(null)
    try {
      const created = await createMutation.mutateAsync(name.trim())
      // Move the plaintext into modal-local state and purge mutation state —
      // the modal is the only plaintext holder (invariant: exactly once).
      setCreatedKey(created)
      createMutation.reset()
      setName("")
    } catch (error: unknown) {
      setCreateError(extractApiKeysErrorMessage(error))
    }
  }

  const handleRevoke = async (key: ApiKeyRead) => {
    setRevokeError(null)
    try {
      await revokeMutation.mutateAsync(key.id)
      setRevokeTarget(null)
    } catch (error: unknown) {
      // 404 = already revoked elsewhere; onSettled re-syncs the list either way.
      setRevokeError(extractApiKeysErrorMessage(error))
    }
  }

  return (
    <section
      data-testid="api-keys-section"
      className="fs-card fs-form-section"
      aria-labelledby="api-keys-heading"
    >
      <header className="fs-form-section__head">
        <h2 id="api-keys-heading" className="fs-form-section__title">API keys</h2>
        <p className="fs-form-section__desc">
          Programmatic access to the {BRAND_NAME} API.
        </p>
      </header>

      {hasApiAccess ? (
        <div className="fs-form-section__body">
          <KeysList
            query={keysQuery}
            onRevoke={(key) => {
              setRevokeError(null)
              setRevokeTarget(key)
            }}
          />

          <form
            onSubmit={(event) => void handleCreate(event)}
            className="fs-key-create"
          >
            <div className="fs-key-create__row">
              <Label htmlFor="api-key-name">Create a new key</Label>
              <Input
                id="api-key-name"
                value={name}
                maxLength={API_KEY_NAME_MAX_LEN}
                placeholder="Key name, e.g. prod-integration"
                onChange={(event) => {
                  setName(event.target.value)
                  if (nameError) setNameError(null)
                }}
                disabled={createMutation.isPending}
                data-testid="api-key-name-input"
              />
              <Button
                type="submit"
                size="sm"
                disabled={createMutation.isPending}
                data-testid="api-key-create"
              >
                {createMutation.isPending ? (
                  <>
                    <Spinner className="mr-2" />
                    Creating...
                  </>
                ) : (
                  "Create key"
                )}
              </Button>
            </div>
            {nameError && (
              <p role="alert" className="fs-error fs-mt-1">
                {nameError}
              </p>
            )}
            {createError && (
              <p
                role="alert"
                className="fs-error fs-mt-1"
                data-testid="api-key-create-error"
              >
                {createError}
              </p>
            )}
          </form>
        </div>
      ) : (
        <UpgradeCta />
      )}

      <CreatedKeyModal createdKey={createdKey} onClose={() => setCreatedKey(null)} />

      <RevokeKeyDialog
        target={revokeTarget}
        isPending={revokeMutation.isPending}
        errorMessage={revokeError}
        onConfirm={(key) => void handleRevoke(key)}
        onClose={() => {
          setRevokeTarget(null)
          setRevokeError(null)
        }}
      />
    </section>
  )
}

// ─── Internals ────────────────────────────────────────────────────────────────

const UpgradeCta: React.FC = () => (
  <div
    data-testid="api-keys-upgrade-cta"
    className="fs-card fs-upsell"
  >
    <div className="fs-row" style={{ gap: "0.85rem" }}>
      <span className="profile-row__avatar" style={{ width: "40px", height: "40px", fontSize: "1rem" }}>
        <KeyRound className="h-5 w-5" />
      </span>
      <div>
        <p className="fs-upsell__title">API access is part of {TRADER_NAME}</p>
        <p className="fs-upsell__text">
          Issue API keys and integrate {BRAND_NAME} signals into your own tools.
        </p>
      </div>
    </div>
    <div className="fs-upsell__actions">
      <Button asChild size="sm">
        <Link to={paths.billing} data-testid="api-keys-upgrade-link">
          Upgrade to {TRADER_NAME}
        </Link>
      </Button>
    </div>
  </div>
)

interface KeysListProps {
  query: ReturnType<typeof useApiKeys>
  onRevoke: (key: ApiKeyRead) => void
}

const KeysList: React.FC<KeysListProps> = ({ query, onRevoke }) => {
  if (query.isPending) {
    return <div className="fs-muted" style={{ padding: "0.5rem 0" }}>Loading API keys…</div>
  }

  if (query.isError) {
    return (
      <div
        role="alert"
        data-testid="api-keys-error"
        className="fs-error"
        style={{ padding: "0.5rem 0" }}
      >
        {extractApiKeysErrorMessage(query.error)}
      </div>
    )
  }

  const keys = query.data ?? []
  if (keys.length === 0) {
    return (
      <div data-testid="api-keys-empty" className="fs-muted" style={{ padding: "0.5rem 0" }}>
        No API keys yet. Create one to call the API.
      </div>
    )
  }

  return (
    <div className="fs-keys">
      {/* Column headers (decorative; rows carry their own labels) */}
      <div className="fs-key-row fs-key-row--head" aria-hidden="true">
        <span>Name</span>
        <span>Key</span>
        <span>Created · Last used</span>
        <span></span>
      </div>
      <ul data-testid="api-keys-list" className="fs-keys__list" aria-label="API keys">
        {keys.map((key) => (
          <ApiKeyRow key={key.id} apiKey={key} onRevoke={onRevoke} />
        ))}
      </ul>
    </div>
  )
}

interface ApiKeyRowProps {
  apiKey: ApiKeyRead
  onRevoke: (key: ApiKeyRead) => void
}

const ApiKeyRow: React.FC<ApiKeyRowProps> = ({ apiKey, onRevoke }) => {
  const revoked = isApiKeyRevoked(apiKey)

  return (
    <li
      data-testid="api-key-row"
      className={`fs-key-row ${revoked ? "fs-key-row--revoked" : ""}`}
    >
      <div className="fs-key-row__name">
        <span className="fs-truncate">{apiKey.name}</span>
        {revoked ? (
          <span data-testid="api-key-revoked-badge" className="fs-badge fs-badge--neutral">
            Revoked
          </span>
        ) : (
          <span className="fs-key-status">Active</span>
        )}
      </div>
      <div className="fs-key-row__key">
        <span className="fs-key-chip">
          <code>{apiKey.prefix}…</code>
        </span>
      </div>
      <div className="fs-key-row__meta">
        Created {formatApiKeyDate(apiKey.created_at)} · Last used{" "}
        {formatApiKeyDate(apiKey.last_used_at)}
      </div>
      <div className="fs-key-row__action">
        {!revoked && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="fs-btn--ghost-danger"
            onClick={() => onRevoke(apiKey)}
            data-testid="api-key-revoke"
          >
            Revoke
          </Button>
        )}
      </div>
    </li>
  )
}
