/**
 * Brand configuration. Override via Vite env at build time:
 *   VITE_BRAND_NAME=TrendPulse
 *   VITE_HELP_URL=https://...
 *   VITE_SUPPORT_EMAIL=support@foresignal.biz
 *
 * Falls back to defaults when env is not set.
 */
const DEFAULT_BRAND_NAME = "TrendPulse"
const DEFAULT_HELP_URL = "https://foresignal.biz/docs"
const DEFAULT_SUPPORT_EMAIL = "support@foresignal.biz"

export const BRAND_NAME: string =
  import.meta.env?.VITE_BRAND_NAME?.trim() || DEFAULT_BRAND_NAME

export const HELP_URL: string =
  import.meta.env?.VITE_HELP_URL?.trim() || DEFAULT_HELP_URL

export const SUPPORT_EMAIL: string =
  import.meta.env?.VITE_SUPPORT_EMAIL?.trim() || DEFAULT_SUPPORT_EMAIL
