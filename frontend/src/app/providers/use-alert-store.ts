import { useContext } from "react"
import { createContext } from "react"
import type { AlertState } from "@/app/stores/alert.store"

type UseAlertStore = <T>(selector: (s: AlertState) => T) => T

export const AlertStoreContext = createContext<UseAlertStore | null>(null)

export function useAlertStore() {
  const context = useContext(AlertStoreContext)

  if (!context) {
    throw new Error("useAlertStore must be used within AlertStoreProvider")
  }

  return context
}
