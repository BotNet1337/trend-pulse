import * as React from "react"

import { BRAND_NAME } from "@/shared/config"
import { cn } from "@/shared/utils/index"

export interface BrandMarkProps extends React.SVGProps<SVGSVGElement> {
  size?: number
  title?: string
}

export const BrandMark: React.FC<BrandMarkProps> = ({
  size = 32,
  title = BRAND_NAME,
  className,
  ...props
}) => {
  const gradientId = React.useId()

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label={title}
      className={cn("block", className)}
      {...props}
    >
      <defs>
        <linearGradient
          id={gradientId}
          x1="0"
          y1="0"
          x2="32"
          y2="32"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#7C3AED" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="7" fill={`url(#${gradientId})`} />
      <path
        d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"
        fill="#FFFFFF"
        transform="translate(4 4)"
      />
    </svg>
  )
}
