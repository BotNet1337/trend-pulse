import * as React from "react"

import { cn } from "@/shared/utils/index"
import { Eye, EyeOff } from "@/shared/images"

import { Input } from "./input"

export interface PasswordInputProps
  extends Omit<React.ComponentProps<"input">, "type"> {
  /** Tooltip / aria-label for the visibility toggle. */
  toggleAriaLabel?: string
}

/**
 * Password input with a show/hide eye toggle pinned to the right edge. Wraps
 * the shared `Input` so spacing, focus ring, disabled state and aria-invalid
 * styles all stay consistent. Pads the input on the right to leave room for
 * the button.
 */
export const PasswordInput: React.FC<PasswordInputProps> = ({
  className,
  disabled,
  toggleAriaLabel,
  ...rest
}) => {
  const [visible, setVisible] = React.useState(false)
  const Icon = visible ? EyeOff : Eye
  const label =
    toggleAriaLabel ?? (visible ? "Hide password" : "Show password")

  return (
    <div className="relative">
      <Input
        {...rest}
        type={visible ? "text" : "password"}
        disabled={disabled}
        className={cn("pr-10", className)}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label={label}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
        disabled={disabled}
        className={cn(
          "absolute inset-y-0 right-0 flex items-center justify-center px-3",
          "text-muted-foreground hover:text-foreground transition-colors",
          "focus-visible:outline-none focus-visible:text-foreground",
          "disabled:pointer-events-none disabled:opacity-50",
          "cursor-pointer",
        )}
      >
        <Icon className="size-4" aria-hidden="true" />
      </button>
    </div>
  )
}
