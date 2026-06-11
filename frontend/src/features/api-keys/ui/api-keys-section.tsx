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
      className="rounded-2xl border border-border bg-background p-6"
    >
      <header className="mb-5 flex flex-col gap-1">
        <h3 className="m-0 text-base font-semibold">API keys</h3>
        <p className="m-0 text-xs text-muted-foreground">
          Programmatic access to the {BRAND_NAME} API.
        </p>
      </header>

      {hasApiAccess ? (
        <div className="flex flex-col gap-5">
          <KeysList
            query={keysQuery}
            onRevoke={(key) => {
              setRevokeError(null)
              setRevokeTarget(key)
            }}
          />

          <form
            onSubmit={(event) => void handleCreate(event)}
            className="flex flex-col gap-2 border-t border-border pt-5"
          >
            <Label htmlFor="api-key-name">Create a new key</Label>
            <div className="grid grid-cols-[1fr_auto] items-center gap-2">
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
                className="min-w-28"
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
              <span role="alert" className="text-xs text-destructive">
                {nameError}
              </span>
            )}
            {createError && (
              <span
                role="alert"
                className="text-xs text-destructive"
                data-testid="api-key-create-error"
              >
                {createError}
              </span>
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
    className="flex flex-col items-start gap-3 rounded-md border border-border bg-secondary/40 p-4 md:flex-row md:items-center md:justify-between"
  >
    <div className="flex items-center gap-3">
      <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <KeyRound className="h-5 w-5" />
      </span>
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold">
          API access is part of {TRADER_NAME}
        </span>
        <span className="text-xs text-muted-foreground">
          Issue API keys and integrate {BRAND_NAME} signals into your own tools.
        </span>
      </div>
    </div>
    <Button asChild size="sm" className="shrink-0">
      <Link to={paths.billing} data-testid="api-keys-upgrade-link">
        Upgrade to {TRADER_NAME}
      </Link>
    </Button>
  </div>
)

interface KeysListProps {
  query: ReturnType<typeof useApiKeys>
  onRevoke: (key: ApiKeyRead) => void
}

const KeysList: React.FC<KeysListProps> = ({ query, onRevoke }) => {
  if (query.isPending) {
    return <div className="py-2 text-sm text-muted-foreground">Loading API keys…</div>
  }

  if (query.isError) {
    return (
      <div
        role="alert"
        data-testid="api-keys-error"
        className="py-2 text-sm text-destructive"
      >
        {extractApiKeysErrorMessage(query.error)}
      </div>
    )
  }

  const keys = query.data ?? []
  if (keys.length === 0) {
    return (
      <div data-testid="api-keys-empty" className="py-2 text-sm text-muted-foreground">
        No API keys yet. Create one to call the API.
      </div>
    )
  }

  return (
    <ul data-testid="api-keys-list" className="m-0 flex list-none flex-col gap-3 p-0">
      {keys.map((key) => (
        <ApiKeyRow key={key.id} apiKey={key} onRevoke={onRevoke} />
      ))}
    </ul>
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
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-border px-4 py-3 ${
        revoked ? "opacity-60" : ""
      }`}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-semibold">{apiKey.name}</span>
          {revoked && (
            <span
              data-testid="api-key-revoked-badge"
              className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.05em] text-muted-foreground"
            >
              Revoked
            </span>
          )}
        </span>
        <span className="font-mono text-xs text-muted-foreground">
          {apiKey.prefix}…
        </span>
        <span className="text-xs text-muted-foreground">
          Created {formatApiKeyDate(apiKey.created_at)} · Last used{" "}
          {formatApiKeyDate(apiKey.last_used_at)}
        </span>
      </div>
      {!revoked && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="min-h-11 shrink-0 text-destructive hover:text-destructive"
          onClick={() => onRevoke(apiKey)}
          data-testid="api-key-revoke"
        >
          Revoke
        </Button>
      )}
    </li>
  )
}
