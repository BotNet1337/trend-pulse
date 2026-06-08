import React from "react"

export interface UseCooldownResult {
  secondsLeft: number
  isActive: boolean
  start: (seconds?: number) => void
  stop: () => void
}

export const useCooldown = (defaultSeconds: number): UseCooldownResult => {
  const [secondsLeft, setSecondsLeft] = React.useState(0)
  const intervalRef = React.useRef<number | null>(null)

  const stop = React.useCallback(() => {
    if (intervalRef.current) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    setSecondsLeft(0)
  }, [])

  const start = React.useCallback(
    (seconds?: number) => {
      const next = seconds ?? defaultSeconds

      if (!Number.isFinite(next) || next <= 0) {
        stop()
        return
      }

      if (intervalRef.current) {
        window.clearInterval(intervalRef.current)
      }

      setSecondsLeft(next)

      intervalRef.current = window.setInterval(() => {
        setSecondsLeft((prev) => {
          if (prev <= 1) {
            if (intervalRef.current) {
              window.clearInterval(intervalRef.current)
              intervalRef.current = null
            }

            return 0
          }

          return prev - 1
        })
      }, 1000)
    },
    [defaultSeconds, stop]
  )

  React.useEffect(() => {
    return () => {
      if (intervalRef.current) {
        window.clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [])

  return {
    secondsLeft,
    isActive: secondsLeft > 0,
    start,
    stop,
  }
}


