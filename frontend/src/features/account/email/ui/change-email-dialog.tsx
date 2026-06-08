import * as React from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

import { Button } from "@/shared/components/button"
import { Input } from "@/shared/components/input"
import { PasswordInput } from "@/shared/components/password-input"
import { Label } from "@/shared/components/label"
import { Spinner } from "@/shared/components/spinner"
import { ModalDialog } from "@/shared/components/modal-dialog"

import { useRequestEmailChange } from "../model"
import {
  changeEmailFormSchema,
  type ChangeEmailFormSchema,
} from "../schema"

export interface ChangeEmailDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  currentEmail: string
}

const defaultValues: ChangeEmailFormSchema = {
  newEmail: "",
  currentPassword: "",
}

type DialogStep =
  | { step: "form" }
  | { step: "sent"; sentTo: string }

export const ChangeEmailDialog: React.FC<ChangeEmailDialogProps> = ({
  open,
  onOpenChange,
  currentEmail,
}) => {
  const [state, setState] = React.useState<DialogStep>({ step: "form" })

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isValid },
  } = useForm<ChangeEmailFormSchema>({
    resolver: zodResolver(changeEmailFormSchema),
    defaultValues,
    mode: "onChange",
  })

  const mutation = useRequestEmailChange({
    onSuccess: (newEmail) => {
      setState({ step: "sent", sentTo: newEmail })
    },
  })

  React.useEffect(() => {
    if (!open) {
      reset(defaultValues)
      setState({ step: "form" })
    }
  }, [open, reset])

  const onOpenChangeSafe = (next: boolean) => {
    if (!next && mutation.isPending) return
    onOpenChange(next)
  }

  const onSubmit = async (data: ChangeEmailFormSchema) => {
    if (data.newEmail.toLowerCase() === currentEmail.toLowerCase()) {
      setError("newEmail", {
        type: "manual",
        message: "New email must be different from the current one",
      })
      return
    }

    await mutation.mutateAsync({
      newEmail: data.newEmail,
      currentPassword: data.currentPassword,
    })
  }

  const title = state.step === "form" ? "Change email" : "Confirmation sent"
  const description =
    state.step === "form"
      ? "Enter your new email address. We'll send a confirmation link to verify it."
      : undefined

  return (
    <ModalDialog
      open={open}
      onOpenChange={onOpenChangeSafe}
      width="md"
      title={title}
      description={description}
    >
      {state.step === "form" ? (
        <form
          data-testid="change-email-dialog"
          className="flex flex-col gap-5"
          onSubmit={handleSubmit(onSubmit)}
        >
          <div className="space-y-2">
            <Label htmlFor="new-email">New email</Label>
            <Input
              id="new-email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              disabled={mutation.isPending}
              {...register("newEmail")}
              className="h-11"
              data-testid="change-email-new-email"
            />
            {errors.newEmail && (
              <p className="text-sm text-destructive">
                {errors.newEmail.message}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="current-password-email">Current password</Label>
            <PasswordInput
              id="current-password-email"
              autoComplete="current-password"
              placeholder="••••••••"
              disabled={mutation.isPending}
              {...register("currentPassword")}
              className="h-11"
              data-testid="change-email-current-password"
            />
            {errors.currentPassword && (
              <p className="text-sm text-destructive">
                {errors.currentPassword.message}
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
              data-testid="change-email-confirm"
            >
              {mutation.isPending ? (
                <>
                  <Spinner className="mr-2" />
                  Sending...
                </>
              ) : (
                "Send confirmation"
              )}
            </Button>
          </div>
        </form>
      ) : (
        <div
          data-testid="change-email-sent"
          className="flex flex-col gap-5"
        >
          <p className="m-0 text-sm text-foreground">
            Check your inbox at <strong>{state.sentTo}</strong>. Click the link
            in the email to finish updating your account email. The link is
            valid for 24 hours.
          </p>
          <p className="m-0 text-xs text-muted-foreground">
            Your sign-in email stays as <strong>{currentEmail}</strong> until
            you confirm.
          </p>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="brand"
              onClick={() => onOpenChange(false)}
            >
              Close
            </Button>
          </div>
        </div>
      )}
    </ModalDialog>
  )
}
