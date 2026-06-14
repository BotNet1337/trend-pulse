import * as React from "react"

import { cn } from "@/shared/utils/index"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        // Aurora design system field (`.fs-input`). aria-invalid styling is
        // handled by the `.fs-input[aria-invalid="true"]` rule in app.css.
        "fs-input",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
        className
      )}
      {...props}
    />
  )
}

export { Input }
