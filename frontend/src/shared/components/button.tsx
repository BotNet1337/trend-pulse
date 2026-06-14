import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/shared/utils/index"

// Aurora design system: buttons are pill-shaped glass/gradient controls
// (`.fs-btn`). CVA variants map to the `.fs-btn--*` modifiers defined in
// app.css so every consumer matches the Foresignal app mockups. The shadcn
// variant/size API is preserved unchanged.
const buttonVariants = cva(
  "fs-btn [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "fs-btn--primary",
        brand: "fs-btn--primary",
        destructive: "fs-btn--danger",
        outline: "fs-btn--secondary",
        secondary: "fs-btn--secondary",
        ghost: "fs-btn--ghost",
        link: "fs-btn--ghost",
      },
      size: {
        default: "",
        sm: "fs-btn--sm",
        lg: "",
        icon: "fs-btn--sm",
        "icon-sm": "fs-btn--sm",
        "icon-lg": "",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button }
