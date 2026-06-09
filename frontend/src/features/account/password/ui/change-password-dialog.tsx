import * as React from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

import { Button } from "@/shared/components/button"
import { PasswordInput } from "@/shared/components/password-input"
import { Label } from "@/shared/components/label"
import { Spinner } from "@/shared/components/spinner"
import { ModalDialog } from "@/shared/components/modal-dialog"

import { useChangePassword } from "../model"
import {
  changePasswordFormSchema,
  type ChangePasswordFormSchema,
} from "../schema"

export interface ChangePasswordDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const defaultValues: ChangePasswordFormSchema = {
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
}

export const ChangePasswordDialog: React.FC<ChangePasswordDialogProps> = ({
  open,
  onOpenChange,
}) => {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isValid },
  } = useForm<ChangePasswordFormSchema>({
    resolver: zodResolver(changePasswordFormSchema),
    defaultValues,
    mode: "onChange",
  })

  const mutation = useChangePassword({
    onSuccess: () => {
      reset(defaultValues)
      onOpenChange(false)
    },
  })

  React.useEffect(() => {
    if (!open) reset(defaultValues)
  }, [open, reset])

  const onOpenChangeSafe = (next: boolean) => {
    if (!next && mutation.isPending) return
    onOpenChange(next)
  }

  const onSubmit = async (data: ChangePasswordFormSchema) => {
    await mutation.mutateAsync({
      currentPassword: data.currentPassword,
      newPassword: data.newPassword,
    })
  }

  return (
    <ModalDialog
      open={open}
      onOpenChange={onOpenChangeSafe}
      width="md"
      title="Change password"
      description="Enter your current password and choose a new one."
    >
      <form
        data-testid="change-password-dialog"
        className="flex flex-col gap-5"
        onSubmit={handleSubmit(onSubmit)}
      >
        <div className="space-y-2">
          <Label htmlFor="current-password">Current password</Label>
          <PasswordInput
            id="current-password"
            autoComplete="current-password"
            placeholder="••••••••"
            disabled={mutation.isPending}
            {...register("currentPassword")}
            className="h-11"
          />
          {errors.currentPassword && (
            <p className="text-sm text-destructive">
              {errors.currentPassword.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="new-password">New password</Label>
          <PasswordInput
            id="new-password"
            autoComplete="new-password"
            placeholder="••••••••"
            disabled={mutation.isPending}
            {...register("newPassword")}
            className="h-11"
          />
          {errors.newPassword && (
            <p className="text-sm text-destructive">
              {errors.newPassword.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="confirm-password">Confirm new password</Label>
          <PasswordInput
            id="confirm-password"
            autoComplete="new-password"
            placeholder="••••••••"
            disabled={mutation.isPending}
            {...register("confirmPassword")}
            className="h-11"
          />
          {errors.confirmPassword && (
            <p className="text-sm text-destructive">
              {errors.confirmPassword.message}
            </p>
          )}
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
            type="submit"
            variant="brand"
            className="h-10"
            disabled={!isValid || mutation.isPending}
            data-testid="change-password-confirm"
          >
            {mutation.isPending ? (
              <>
                <Spinner className="mr-2" />
                Updating...
              </>
            ) : (
              "Update password"
            )}
          </Button>
        </div>
      </form>
    </ModalDialog>
  )
}
