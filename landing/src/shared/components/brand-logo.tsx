import * as React from 'react';

let uid = 0;

/**
 * Foresignal brand mark — gradient signal glyph, ported 1:1 from the Aurora
 * landing mockups (designs/trendPulse/landing). Each instance gets a unique
 * gradient id so multiple logos on one page don't collide.
 */
export function BrandLogo({ size = 30, title = 'Foresignal logo' }: { size?: number; title?: string }) {
  const gradId = React.useMemo(() => `fs-logo-grad-${++uid}`, []);
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" role="img" aria-label={title}>
      <defs>
        <linearGradient id={gradId} x1="2" y1="30" x2="30" y2="2" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2563eb" />
          <stop offset="0.5" stopColor="#7c3aed" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect x="1.5" y="1.5" width="29" height="29" rx="9" stroke={`url(#${gradId})`} strokeWidth="2" />
      <path
        d="M6.5 19.5 L11 19.5 L13.5 10.5 L17.5 23 L20 14.5 L21.8 19.5 L25.5 19.5"
        stroke={`url(#${gradId})`}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}
