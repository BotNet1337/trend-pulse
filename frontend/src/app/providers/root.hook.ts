import { useContext } from 'react'
import { RootContext } from './root.context'

export function useRoot() {
  const ctx = useContext(RootContext)
  if (!ctx) throw new Error('useRoot must be used within AppProvider')
  return ctx
}


