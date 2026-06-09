import * as React from "react"
import { ErrorBoundary, type FallbackProps } from "react-error-boundary"
import { Button } from "@/shared/components/button"

/**
 * Root-level error boundary (TASK-AUDIT-RELEASE-1 / H12).
 *
 * Catches uncaught render-time exceptions from any feature so a bug in one
 * page does not blank the whole app. The fallback offers a "Try again"
 * (resets the boundary) and a hard reload — the latter clears whatever
 * in-memory state caused the crash.
 */
const Fallback: React.FC<FallbackProps> = ({ error, resetErrorBoundary }) => {
  return (
    <div className="auth-light min-h-dvh flex items-center justify-center bg-background text-foreground px-6">
      <div className="flex flex-col items-center gap-4 max-w-md text-center">
        <span
          aria-hidden="true"
          className="inline-flex size-16 items-center justify-center rounded-full bg-destructive-soft text-destructive text-3xl font-bold"
        >
          !
        </span>
        <h1 className="m-0 text-2xl font-bold tracking-[-0.02em]">
          Something went wrong
        </h1>
        <p className="m-0 text-sm text-muted-foreground">
          {error instanceof Error
            ? error.message
            : "Unexpected error. Please try again."}
        </p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={resetErrorBoundary}>
            Try again
          </Button>
          <Button
            type="button"
            variant="brand"
            onClick={() => {
              if (typeof window !== "undefined") window.location.reload()
            }}
          >
            Reload
          </Button>
        </div>
      </div>
    </div>
  )
}

interface GlobalErrorBoundaryProps {
  children: React.ReactNode
}

const onError = (error: unknown, info: React.ErrorInfo): void => {
  // No Sentry wired up yet (see TASK-AUDIT-OPS / C10). Until then, surface
  // the crash via console so it shows up in browser logs / SSR pino.
  console.error("[GlobalErrorBoundary]", error, info.componentStack)
}

export const GlobalErrorBoundary: React.FC<GlobalErrorBoundaryProps> = ({
  children,
}) => {
  return (
    <ErrorBoundary FallbackComponent={Fallback} onError={onError}>
      {children}
    </ErrorBoundary>
  )
}
