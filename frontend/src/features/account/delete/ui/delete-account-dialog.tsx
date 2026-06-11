import * as React from "react"

import { Button } from "@/shared/components/button"
import { Input } from "@/shared/components/input"
import { Label } from "@/shared/components/label"
import { Spinner } from "@/shared/components/spinner"
import { ModalDialog } from "@/shared/components/modal-dialog"
import { Trash2 } from "@/shared/images"

import { useDeleteAccount } from "../model"
import { DELETE_ACCOUNT_DESCRIPTION } from "./copy"

export interface DeleteAccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Currently-authenticated userId. */
  userId: string
  /** Email used for confirmation phrase. */
  email: string
}

export const DeleteAccountDialog: React.FC<DeleteAccountDialogProps> = ({
  open,
  onOpenChange,
  // userId kept in props for future use (task-014)
  userId: _userId,
  email,
}) => {
  const [confirmText, setConfirmText] = React.useState("")

  const mutation = useDeleteAccount({
    onSuccess: () => {
      onOpenChange(false)
    },
  })

  React.useEffect(() => {
    if (!open) setConfirmText("")
  }, [open])

  const expected = email.trim()
  const canDelete =
    expected.length > 0 &&
    confirmText.trim() === expected &&
    !mutation.isPending

  const onOpenChangeSafe = (next: boolean) => {
    if (!next && mutation.isPending) return
    onOpenChange(next)
  }

  return (
    <ModalDialog
      open={open}
      onOpenChange={onOpenChangeSafe}
      width="confirm"
      dangerHeader={{ icon: <Trash2 /> }}
      title="Delete account?"
      description={DELETE_ACCOUNT_DESCRIPTION}
    >
      <div data-testid="delete-account-dialog" className="flex flex-col gap-5">
        <div className="space-y-2">
          <Label htmlFor="account-delete-confirm">
            Type{" "}
            <span className="font-mono text-foreground">{expected}</span> to
            confirm
          </Label>
          <Input
            id="account-delete-confirm"
            type="email"
            value={confirmText}
            onChange={(event) => setConfirmText(event.target.value)}
            disabled={mutation.isPending}
            placeholder={expected}
            autoFocus
            className="h-11 focus-visible:border-destructive focus-visible:ring-destructive/20"
          />
        </div>

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChangeSafe(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            className="h-10"
            onClick={() => {
              if (!canDelete) return
              mutation.mutate()
            }}
            disabled={!canDelete}
            data-testid="delete-account-confirm"
          >
            {mutation.isPending ? (
              <>
                <Spinner className="mr-2" />
                Deleting...
              </>
            ) : (
              "Delete account"
            )}
          </Button>
        </div>
      </div>
    </ModalDialog>
  )
}
