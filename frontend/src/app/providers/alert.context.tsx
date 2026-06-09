import React, { useMemo } from "react"
import type { AlertStore } from "@/app/stores/alert.store"
import { createUseAlertStore } from "@/app/stores/alert.store"
import { AlertStoreContext } from "./use-alert-store"

export interface AlertStoreProviderProps {
  store: AlertStore
  children: React.ReactNode
}

export function AlertStoreProvider({ store, children }: AlertStoreProviderProps) {
  const useAlertStore = useMemo(() => createUseAlertStore(store), [store])

  return (
    <AlertStoreContext.Provider value={useAlertStore}>
      {children}
    </AlertStoreContext.Provider>
  )
}
