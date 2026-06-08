import * as React from "react"

/**
 * Returns `false` during SSR and the very first client render, then flips to
 * `true` after `useEffect` runs (post-mount).
 *
 * Use this to gate code that produces output dependent on the client
 * environment — local timezone, locale-specific date formatting, browser
 * APIs, etc. Both server and initial client render see `false`, so the
 * markup matches and React's hydration succeeds without warnings; the
 * post-mount re-render then upgrades to the real value.
 */
export const useIsMounted = (): boolean => {
  const [mounted, setMounted] = React.useState(false)
  React.useEffect(() => {
    setMounted(true)
  }, [])
  return mounted
}
