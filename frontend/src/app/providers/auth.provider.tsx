import React, { useMemo } from 'react'
import { createUseAuthStore, type AuthStore } from '../stores/auth.store'
import { AuthContext } from './use-auth'

export interface AuthProviderProps {
  auth: AuthStore
  children: React.ReactNode
}

export function AuthProvider(props: AuthProviderProps) {
  const useAuth = useMemo(() => createUseAuthStore(props.auth), [props.auth])

  return (
    <AuthContext.Provider value={useAuth}>
      {props.children}
    </AuthContext.Provider>
  )
}
