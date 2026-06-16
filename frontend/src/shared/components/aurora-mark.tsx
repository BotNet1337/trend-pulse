import * as React from 'react'

import { BRAND_NAME } from '@/shared/config'

export interface AuroraMarkProps extends React.SVGProps<SVGSVGElement> {
  size?: number
  title?: string
}

/**
 * Aurora brand mark — the gradient pulse-wave logo from the Foresignal app
 * design (designs/trendPulse/variants/app).
 *
 * The gradient id is a STABLE constant, NOT `useId()`: under SSR the server
 * (TanStack `renderRouterToString`) and the client (`hydrateRoot`) wrap the app
 * differently, so `useId()` yields different values on each side; this mark is the
 * first id-consumer rendered, so that divergence trips a hydration mismatch
 * (React #418) on every page. The gradient is decorative and identical for every
 * instance, so a shared id is safe (a duplicate decorative `<linearGradient>`
 * resolves to the same visual result).
 */
const AURORA_MARK_GRADIENT_ID = 'fs-aurora-mark-gradient'

export const AuroraMark: React.FC<AuroraMarkProps> = ({
  size = 32,
  title = `${BRAND_NAME} logo`,
  ...props
}) => {
  const gradientId = AURORA_MARK_GRADIENT_ID

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role="img"
      aria-label={title}
      {...props}
    >
      <defs>
        <linearGradient
          id={gradientId}
          x1="2"
          y1="30"
          x2="30"
          y2="2"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0" stopColor="#2563eb" />
          <stop offset="0.5" stopColor="#7c3aed" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect
        x="1.5"
        y="1.5"
        width="29"
        height="29"
        rx="9"
        stroke={`url(#${gradientId})`}
        strokeWidth="2"
      />
      <path
        d="M6.5 19.5 L11 19.5 L13.5 10.5 L17.5 23 L20 14.5 L21.8 19.5 L25.5 19.5"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  )
}
