import * as React from "react"

import { AppHealthContext, type AppHealthContextValue } from "./health.context"

export const useAppHealth = (): AppHealthContextValue => {
  const ctx = React.useContext(AppHealthContext)
  if (!ctx) throw new Error("useAppHealth must be used within AppHealthProvider")
  return ctx
}
