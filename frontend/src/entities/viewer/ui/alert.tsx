import React from "react"
import { Alert as AlertPrimitive, AlertTitle, AlertDescription } from "@/shared/components/alert"
import { CheckCircle2, XCircle, X } from "@/shared/images"
import { cn } from "@/shared/utils"
import type { AlertItem, AlertType } from "../model"

const iconByType: Record<AlertType, React.ReactNode> = {
  success: <CheckCircle2 className="size-4" />,
  error: <XCircle className="size-4" />,
}

interface AlertProps {
  item: AlertItem
  onRemove: (id: string) => void
  className?: string
}

export const Alert: React.FC<AlertProps> = ({ item, onRemove, className }) => {
  return (
    <AlertPrimitive
      variant={item.type === "error" ? "destructive" : "default"}
      className={cn("shadow-lg pr-8", className)}
    >
      {iconByType[item.type]}
      <div className="flex-1 min-w-0">
        <AlertTitle>{item.title}</AlertTitle>
        {item.description && (
          <AlertDescription>{item.description}</AlertDescription>
        )}
      </div>
      <button
        onClick={() => onRemove(item.id)}
        className="absolute right-3 top-3 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:pointer-events-none"
        aria-label="Close alert"
      >
        <X className="size-4" />
      </button>
    </AlertPrimitive>
  )
}

