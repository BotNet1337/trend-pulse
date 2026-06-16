import * as React from "react"

/**
 * Google reCAPTCHA v2 ("I'm not a robot") widget.
 *
 * Prod-only by design: the widget renders ONLY when `VITE_RECAPTCHA_SITE_KEY` is
 * baked into the bundle at build time. Local dev leaves it unset, so the component
 * renders nothing and `RECAPTCHA_ENABLED` is false — no captcha challenge locally.
 *
 * The matching secret lives only on the backend (RECAPTCHA_SECRET_KEY); this
 * component never sees it. On solve, `onChange` receives the client token to send
 * in the sign-up payload; on expiry/error it receives null.
 */

const SITE_KEY: string = import.meta.env?.VITE_RECAPTCHA_SITE_KEY?.trim() || ""
const SCRIPT_ID = "recaptcha-v2-script"
const SCRIPT_SRC = "https://www.google.com/recaptcha/api.js?render=explicit"
const POLL_MS = 200

/** True when a reCAPTCHA site key is configured (prod). False in local dev. */
export const RECAPTCHA_ENABLED: boolean = SITE_KEY.length > 0

interface GReCaptcha {
  render: (
    el: HTMLElement,
    options: {
      sitekey: string
      callback: (token: string) => void
      "expired-callback": () => void
      "error-callback": () => void
    },
  ) => number
  reset: (widgetId?: number) => void
}

declare global {
  interface Window {
    grecaptcha?: GReCaptcha
  }
}

export interface RecaptchaProps {
  /** Called with the token on solve, or null on expiry/error. */
  onChange: (token: string | null) => void
}

export const Recaptcha: React.FC<RecaptchaProps> = ({ onChange }) => {
  const containerRef = React.useRef<HTMLDivElement>(null)
  const widgetIdRef = React.useRef<number | null>(null)
  // Keep the latest onChange without re-running the (render-once) effect below.
  const onChangeRef = React.useRef(onChange)
  React.useEffect(() => {
    onChangeRef.current = onChange
  })

  React.useEffect(() => {
    if (!RECAPTCHA_ENABLED) return
    let cancelled = false
    let pollId: number | undefined

    const renderWidget = () => {
      if (cancelled || widgetIdRef.current !== null) return
      const grecaptcha = window.grecaptcha
      const el = containerRef.current
      if (!grecaptcha?.render || !el) return
      widgetIdRef.current = grecaptcha.render(el, {
        sitekey: SITE_KEY,
        callback: (token: string) => onChangeRef.current(token),
        "expired-callback": () => onChangeRef.current(null),
        "error-callback": () => onChangeRef.current(null),
      })
    }

    if (window.grecaptcha?.render) {
      renderWidget()
    } else {
      if (!document.getElementById(SCRIPT_ID)) {
        const script = document.createElement("script")
        script.id = SCRIPT_ID
        script.src = SCRIPT_SRC
        script.async = true
        script.defer = true
        document.head.appendChild(script)
      }
      // The api.js onload global is awkward to share; poll for readiness instead.
      pollId = window.setInterval(() => {
        if (window.grecaptcha?.render) {
          window.clearInterval(pollId)
          renderWidget()
        }
      }, POLL_MS)
    }

    return () => {
      cancelled = true
      if (pollId !== undefined) window.clearInterval(pollId)
    }
  }, [])

  if (!RECAPTCHA_ENABLED) return null
  return <div ref={containerRef} className="fs-field" aria-label="CAPTCHA verification" />
}
