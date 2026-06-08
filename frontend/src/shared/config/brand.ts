/**
 * Brand configuration. Override via Vite env at build time:
 *   VITE_BRAND_NAME=MyBrand
 *   VITE_HELP_URL=https://...
 *
 * Falls back to "PostBolt" so the app boots cleanly without a custom env.
 */
const DEFAULT_BRAND_NAME = "PostBolt"
const DEFAULT_HELP_URL = "https://postbolt.io/docs"

export const BRAND_NAME: string =
  import.meta.env?.VITE_BRAND_NAME?.trim() || DEFAULT_BRAND_NAME

export const HELP_URL: string =
  import.meta.env?.VITE_HELP_URL?.trim() || DEFAULT_HELP_URL
