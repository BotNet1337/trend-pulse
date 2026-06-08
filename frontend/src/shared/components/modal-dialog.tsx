import * as React from "react"

import { Button } from "./button"
import { X } from "@/shared/images"
import { cn } from "@/shared/utils/index"

export type ModalDialogWidth = "sm" | "md" | "lg" | "xl" | "confirm"

export interface ModalDialogDangerHeader {
  /** Icon rendered inside the destructive 64×64 circle. */
  icon: React.ReactNode
}

export interface ModalDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title?: React.ReactNode
  description?: React.ReactNode
  children: React.ReactNode
  /** Width preset; defaults to "md" (max-w-md). */
  width?: ModalDialogWidth
  /** Hide the close button (e.g. confirmation dialogs). */
  hideClose?: boolean
  /** When set, renders a destructive icon header above the title. */
  dangerHeader?: ModalDialogDangerHeader
}

const widthClass: Record<ModalDialogWidth, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-[720px]",
  confirm: "max-w-[640px]",
}

export const ModalDialog: React.FC<ModalDialogProps> = ({
  open,
  onOpenChange,
  title,
  description,
  children,
  width = "md",
  hideClose,
  dangerHeader,
}) => {
  // ESC closes
  React.useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("keydown", handler)
    return () => document.removeEventListener("keydown", handler)
  }, [open, onOpenChange])

  // Lock body scroll while open
  React.useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? "modal-dialog-title" : undefined}
      aria-describedby={description ? "modal-dialog-desc" : undefined}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-[2px] animate-in fade-in"
        onClick={() => onOpenChange(false)}
      />
      <div
        className={cn(
          "relative w-full bg-card text-card-foreground rounded-xl border border-border shadow-2xl p-6 animate-in fade-in zoom-in-95",
          widthClass[width],
        )}
      >
        {!hideClose && (
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label="Close"
            className="absolute top-3 right-3"
            onClick={() => onOpenChange(false)}
          >
            <X className="h-4 w-4" />
          </Button>
        )}
        {dangerHeader && (
          <div className="flex justify-center mb-4">
            <div
              aria-hidden="true"
              className="size-16 rounded-full bg-destructive/10 text-destructive inline-flex items-center justify-center [&_svg]:size-7"
            >
              {dangerHeader.icon}
            </div>
          </div>
        )}
        {(title || description) && (
          <div
            className={cn(
              "flex flex-col gap-1.5 mb-5",
              dangerHeader ? "items-center text-center" : "pr-8",
            )}
          >
            {title && (
              <h2
                id="modal-dialog-title"
                className="text-lg font-semibold tracking-[-0.01em]"
              >
                {title}
              </h2>
            )}
            {description && (
              <p
                id="modal-dialog-desc"
                className="text-sm text-muted-foreground leading-[1.5]"
              >
                {description}
              </p>
            )}
          </div>
        )}
        {children}
      </div>
    </div>
  )
}
