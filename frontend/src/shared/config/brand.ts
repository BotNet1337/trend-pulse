/**
 * Brand configuration. Override via Vite env at build time:
 *   VITE_BRAND_NAME=TrendPulse
 *   VITE_HELP_URL=https://...
 *
 * Falls back to "TrendPulse" (the product name) when env is not set.
 */
const DEFAULT_BRAND_NAME = "TrendPulse"
const DEFAULT_HELP_URL = "https://trendpulse.app/docs"

export const BRAND_NAME: string =
  import.meta.env?.VITE_BRAND_NAME?.trim() || DEFAULT_BRAND_NAME

export const HELP_URL: string =
  import.meta.env?.VITE_HELP_URL?.trim() || DEFAULT_HELP_URL
