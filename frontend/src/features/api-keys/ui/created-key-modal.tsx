import * as React from "react"

import { Button } from "@/shared/components/button"
import { ModalDialog } from "@/shared/components/modal-dialog"
import { CheckCircle2, Copy } from "@/shared/images"

import type { ApiKeyCreated } from "../api"

export interface CreatedKeyModalProps {
  /** Freshly created key (the ONLY plaintext carrier); null = closed. */
  createdKey: ApiKeyCreated | null
  /** Close = conscious loss of the plaintext (mirrors backend "exactly once"). */
  onClose: () => void
}

const COPY_FAILED_MESSAGE =
  "Copy failed — select the key text and copy it manually."

/**
 * One-time plaintext reveal modal (TASK-065 AC2).
 *
 * The plaintext lives ONLY in the parent's local React state while this modal
 * is open. Closing it (button, Esc, backdrop) discards the secret forever —
 * the warning copy makes that explicit.
 */
export const CreatedKeyModal: React.FC<CreatedKeyModalProps> = ({
  createdKey,
  onClose,
}) => {
  const [copied, setCopied] = React.useState(false)
  const [copyError, setCopyError] = React.useState<string | null>(null)

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setCopied(false)
      setCopyError(null)
      onClose()
    }
  }

  const handleCopy = async () => {
    if (!createdKey) return
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable")
      await navigator.clipboard.writeText(createdKey.key)
      setCopied(true)
      setCopyError(null)
    } catch {
      // Insecure context / old browser: the key stays selectable below.
      setCopyError(COPY_FAILED_MESSAGE)
    }
  }

  return (
    <ModalDialog
      open={createdKey !== null}
      onOpenChange={handleOpenChange}
      width="confirm"
      title="API key created"
      description="Copy your key now — for security reasons you won't see it again."
    >
      {createdKey && (
        <div data-testid="api-key-created-modal" className="flex flex-col gap-4">
          <div className="grid grid-cols-[1fr_auto] items-center gap-2">
            <code
              data-testid="api-key-plaintext"
              className="block min-w-0 select-all break-all rounded-md border border-border bg-secondary/40 px-3 py-2.5 font-mono text-sm"
            >
              {createdKey.key}
            </code>
            <Button
              type="button"
              variant="outline"
              className="h-11 min-w-24"
              onClick={() => void handleCopy()}
              data-testid="api-key-copy"
            >
              {copied ? (
                <>
                  <CheckCircle2 className="mr-1.5 h-4 w-4" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="mr-1.5 h-4 w-4" />
                  Copy
                </>
              )}
            </Button>
          </div>

          {copyError && (
            <p role="alert" className="m-0 text-xs text-destructive">
              {copyError}
            </p>
          )}

          <p className="m-0 text-xs text-muted-foreground">
            This is the only time the full key is shown. Store it in a secure
            place — the list below will only show its prefix.
          </p>

          <div className="flex justify-end">
            <Button
              type="button"
              onClick={() => handleOpenChange(false)}
              data-testid="api-key-created-done"
            >
              I&apos;ve copied the key
            </Button>
          </div>
        </div>
      )}
    </ModalDialog>
  )
}
