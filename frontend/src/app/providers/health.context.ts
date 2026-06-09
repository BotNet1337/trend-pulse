import * as React from "react"

export type HealthStatus = "checking" | "ok" | "down"

export interface AppHealthContextValue {
  status: HealthStatus
  retry: () => void
}

export const AppHealthContext =
  React.createContext<AppHealthContextValue | null>(null)
