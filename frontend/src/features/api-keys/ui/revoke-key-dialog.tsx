import * as React from "react"

import { Button } from "@/shared/components/button"
import { ModalDialog } from "@/shared/components/modal-dialog"
import { Spinner } from "@/shared/components/spinner"
import { Trash2 } from "@/shared/images"

import type { ApiKeyRead } from "../api"

export interface RevokeKeyDialogProps {
  /** Key pending revocation; null = closed. */
  target: ApiKeyRead | null
  isPending: boolean
  /** Error message from a failed revoke attempt (shown inside the dialog). */
  errorMessage: string | null
  onConfirm: (key: ApiKeyRead) => void
  onClose: () => void
}

/** Revoke confirmation dialog (TASK-065 AC3) — pattern: delete-account-dialog. */
export const RevokeKeyDialog: React.FC<RevokeKeyDialogProps> = ({
  target,
  isPending,
  errorMessage,
  onConfirm,
  onClose,
}) => {
  const handleOpenChange = (next: boolean) => {
    if (!next && isPending) return
    if (!next) onClose()
  }

  return (
    <ModalDialog
      open={target !== null}
      onOpenChange={handleOpenChange}
      width="confirm"
      dangerHeader={{ icon: <Trash2 /> }}
      title="Revoke API key?"
      description="Requests using this key will stop working immediately. This cannot be undone."
    >
      {target && (
        <div data-testid="api-key-revoke-dialog" className="flex flex-col gap-4">
          <p className="m-0 text-center text-sm">
            <span className="font-semibold">{target.name}</span>{" "}
            <span className="font-mono text-muted-foreground">
              ({target.prefix}…)
            </span>
          </p>

          {errorMessage && (
            <p role="alert" className="m-0 text-center text-xs text-destructive">
              {errorMessage}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => onConfirm(target)}
              disabled={isPending}
              data-testid="api-key-revoke-confirm"
            >
              {isPending ? (
                <>
                  <Spinner className="mr-2" />
                  Revoking...
                </>
              ) : (
                "Revoke key"
              )}
            </Button>
          </div>
        </div>
      )}
    </ModalDialog>
  )
}
