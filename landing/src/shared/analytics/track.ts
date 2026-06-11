/**
 * Plausible analytics helper — TASK-068.
 *
 * Plausible is cookieless and privacy-first: no cookies, no personal data, so
 * the script itself needs no consent gate. Opt-out is the standard Plausible
 * localStorage flag (PLAUSIBLE_IGNORE_KEY), wired to the cookie banner.
 *
 * track() is a guaranteed no-op when the script is blocked (adblock), disabled
 * (empty plausibleDomain in config.json), or broken — CTA clicks and navigation
 * must never depend on analytics.
 */

/** Plausible Cloud tracker script — the only allowed analytics script source. */
export const PLAUSIBLE_SCRIPT_URL = 'https://plausible.io/js/script.js';

/** Standard Plausible opt-out flag: localStorage[PLAUSIBLE_IGNORE_KEY] = 'true'. */
export const PLAUSIBLE_IGNORE_KEY = 'plausible_ignore';

/** Custom event: any sign-up CTA click (landing hero/final-cta/nav + SPA form). */
export const EVENT_SIGN_UP_CLICK = 'sign_up_click';

/** Custom event: landing /pricing page view (fired once per visit). */
export const EVENT_PRICING_VIEW = 'pricing_view';

type PlausibleFn = (event: string) => void;

declare global {
  interface Window {
    plausible?: PlausibleFn;
  }
}

/** Send a custom event to Plausible. Never throws, never blocks navigation. */
export function track(event: string): void {
  try {
    if (typeof window === 'undefined') return;
    window.plausible?.(event);
  } catch {
    // Analytics must never break UX (blocked/failed script) — swallow.
  }
}
