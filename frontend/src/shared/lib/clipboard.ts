/**
 * Best-effort copy-to-clipboard. Prefers the async Clipboard API; falls back to
 * a hidden `<textarea>` + `execCommand('copy')` for non-secure contexts and
 * older browsers. Returns whether the copy succeeded so callers can drive UI
 * (e.g. a "Copied" confirmation) instead of assuming success.
 *
 * SECURITY: callers pass sensitive one-time values (PAT plaintext) here; the
 * value is only handed to the platform clipboard and never stored or logged.
 */
export const copyToClipboard = async (value: string): Promise<boolean> => {
  if (
    typeof navigator !== "undefined" &&
    navigator.clipboard?.writeText &&
    typeof window !== "undefined" &&
    window.isSecureContext
  ) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // fall through to the legacy path
    }
  }

  if (typeof document === "undefined") return false

  try {
    const textarea = document.createElement("textarea")
    textarea.value = value
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand("copy")
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}
