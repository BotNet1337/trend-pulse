import { createContext, useContext } from 'react'
import type { AuthState } from '../stores/auth.store'

type UseAuth = <T>(selector: (state: AuthState) => T) => T

export const AuthContext = createContext<UseAuth | null>(null)

export function useAuth() {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error("useAuth must be used within AuthProvider")
  }

  return context
}
