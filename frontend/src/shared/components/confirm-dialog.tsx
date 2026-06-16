import * as React from "react"

import { Button } from "./button"
import { ModalDialog } from "./modal-dialog"
import { Spinner } from "./spinner"
import { Trash2 } from "@/shared/images"

export interface ConfirmDialogProps {
  /** Whether the dialog is open. */
  open: boolean
  /** Dialog heading (e.g. "Delete watchlist?"). */
  title: React.ReactNode
  /** Supporting copy under the title. */
  description?: React.ReactNode
  /** Label for the confirm action button. Defaults to "Delete". */
  confirmLabel?: string
  /** Label shown on the confirm button while the action is running. */
  pendingLabel?: string
  /** Disables buttons + shows a spinner on the confirm button. */
  isPending?: boolean
  /** Optional error message rendered inside the dialog. */
  errorMessage?: string | null
  /** Confirm button visual style. Defaults to "destructive". */
  confirmVariant?: "destructive" | "default"
  /** Icon for the danger header circle. Defaults to a trash icon. */
  icon?: React.ReactNode
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Reusable destructive-action confirmation dialog.
 *
 * Wraps ModalDialog with a danger header + Cancel/Confirm buttons and a pending
 * state, so every delete/disconnect across the app shares one consistent,
 * accessible confirmation step (mirrors revoke-key-dialog / delete-account-dialog).
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  title,
  description,
  confirmLabel = "Delete",
  pendingLabel = "Deleting...",
  isPending = false,
  errorMessage,
  confirmVariant = "destructive",
  icon,
  onConfirm,
  onCancel,
}) => {
  const handleOpenChange = (next: boolean) => {
    // Ignore close attempts (backdrop click / ESC) while the action is running.
    if (!next && isPending) return
    if (!next) onCancel()
  }

  return (
    <ModalDialog
      open={open}
      onOpenChange={handleOpenChange}
      width="confirm"
      dangerHeader={{ icon: icon ?? <Trash2 /> }}
      title={title}
      description={description}
    >
      <div className="flex flex-col gap-4">
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
            variant={confirmVariant}
            onClick={onConfirm}
            disabled={isPending}
          >
            {isPending ? (
              <>
                <Spinner className="mr-2" />
                {pendingLabel}
              </>
            ) : (
              confirmLabel
            )}
          </Button>
        </div>
      </div>
    </ModalDialog>
  )
}
