export type StrengthLevel = "weak" | "fair" | "good" | "strong"

export interface PasswordStrength {
  /** Bar fill percentage (0–100). 0 means "no password yet". */
  strength: number
  /** Visible level label. Empty string when password is empty. */
  text: "" | "Weak" | "Fair" | "Good" | "Strong"
  /** Tailwind background class for the legacy bar; kept for back-compat. */
  color: string
  /** Discriminated level for the new `<StrengthBar />` primitive. */
  level: StrengthLevel | null
  /** Per-criterion booleans: [length≥8, mixedCase, number, special]. */
  checks: readonly [boolean, boolean, boolean, boolean]
}

export const usePasswordStrength = (password: string): PasswordStrength => {
  const checks: [boolean, boolean, boolean, boolean] = [
    password.length >= 8,
    /[a-z]/.test(password) && /[A-Z]/.test(password),
    /\d/.test(password),
    /[^a-zA-Z\d]/.test(password),
  ]

  if (!password) {
    return { strength: 0, text: "", color: "", level: null, checks }
  }

  const score = checks.filter(Boolean).length

  if (score <= 1) {
    return { strength: 25, text: "Weak", color: "bg-strength-weak", level: "weak", checks }
  }
  if (score === 2) {
    return { strength: 50, text: "Fair", color: "bg-strength-fair", level: "fair", checks }
  }
  if (score === 3) {
    return { strength: 75, text: "Good", color: "bg-strength-good", level: "good", checks }
  }
  return { strength: 100, text: "Strong", color: "bg-strength-strong", level: "strong", checks }
}
