import * as React from "react"

import { apiClient } from "@/shared/api"

import {
  AppHealthContext,
  type AppHealthContextValue,
  type HealthStatus,
} from "./health.context"

const POLL_INTERVAL_MS = 30_000
const INITIAL_TIMEOUT_MS = 8_000

const probe = async (signal: AbortSignal): Promise<boolean> => {
  try {
    // Ops probes (/health, /ready) are mounted UNVERSIONED at the API root, not
    // under /v1 — override the client's '/api/v1' baseURL so this hits /api/health
    // (otherwise '/api/v1/health' → 404 → the app shows the "temporarily down" screen).
    const response = await apiClient.get("/health", {
      baseURL: "/api",
      signal,
      timeout: 6_000,
    })
    return response.status >= 200 && response.status < 500
  } catch {
    return false
  }
}

export interface AppHealthProviderProps {
  children: React.ReactNode
  /** Component shown while we're still waiting on the first probe. */
  fallback?: React.ReactNode
  /** Component shown when health checks fail. */
  downView?: React.ReactNode
}

const DefaultDownView: React.FC<{ onRetry: () => void }> = ({ onRetry }) => (
  <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-6">
    <div className="flex flex-col items-center gap-4 max-w-md text-center">
      <span
        aria-hidden="true"
        className="inline-flex size-16 items-center justify-center rounded-full bg-destructive-soft text-destructive text-3xl"
      >
        !
      </span>
      <h1 className="m-0 text-2xl font-bold tracking-[-0.02em]">
        Ops, we're temporarily down
      </h1>
      <p className="m-0 text-sm text-muted-foreground">
        Our service is having a moment. We're already on it — please try again
        in a few minutes.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-2 inline-flex h-9 items-center rounded-md border border-border bg-card px-4 text-sm font-medium hover:bg-secondary"
      >
        Retry now
      </button>
    </div>
  </div>
)

const DefaultFallback: React.FC = () => (
  <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground" />
)

/**
 * Wraps the app in a health check. On mount it probes `GET /api/health`; if
 * the probe fails the children are replaced with a "we're temporarily down"
 * page. Subsequent polling brings the app back automatically once the API
 * recovers — no manual reload needed.
 */
export const AppHealthProvider: React.FC<AppHealthProviderProps> = ({
  children,
  fallback,
  downView,
}) => {
  const [status, setStatus] = React.useState<HealthStatus>("ok")
  const tickRef = React.useRef(0)

  const runProbe = React.useCallback((signal: AbortSignal, isInitial: boolean) => {
    const myTick = ++tickRef.current
    void probe(signal).then((ok) => {
      if (signal.aborted || myTick !== tickRef.current) return
      setStatus(
        ok
          ? "ok"
          : isInitial
            ? "down"
            : (prev) => (prev === "ok" ? "ok" : "down"),
      )
    })
  }, [])

  React.useEffect(() => {
    const controller = new AbortController()
    runProbe(controller.signal, true)

    const initialTimer = setTimeout(() => {
      setStatus((prev) => (prev === "checking" ? "down" : prev))
    }, INITIAL_TIMEOUT_MS)

    const interval = setInterval(() => {
      const c = new AbortController()
      runProbe(c.signal, false)
    }, POLL_INTERVAL_MS)

    return () => {
      controller.abort()
      clearTimeout(initialTimer)
      clearInterval(interval)
    }
  }, [runProbe])

  const retry = React.useCallback(() => {
    setStatus("checking")
    const controller = new AbortController()
    runProbe(controller.signal, true)
  }, [runProbe])

  const value = React.useMemo<AppHealthContextValue>(
    () => ({ status, retry }),
    [status, retry],
  )

  let body: React.ReactNode
  if (status === "checking") {
    body = fallback ?? <DefaultFallback />
  } else if (status === "down") {
    body = downView ?? <DefaultDownView onRetry={retry} />
  } else {
    body = children
  }

  return (
    <AppHealthContext.Provider value={value}>{body}</AppHealthContext.Provider>
  )
}
